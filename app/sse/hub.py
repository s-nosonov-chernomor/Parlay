# app/sse/hub.py
from __future__ import annotations

import asyncio
import json
import time
import threading
from dataclasses import dataclass
from typing import Optional

from app.metrics import active_sse_connections


@dataclass
class Change:
    topic: str
    ts: str  # ISO timestamp
    value_num: float | None
    value_text: str | None
    status_code: int | None
    updated_at: str  # ISO timestamp


@dataclass
class Event:
    id: int
    ts: str
    changes: list[Change]

@dataclass
class UiStateChange:
    ui_id: str
    mode_effective: str
    mode_requested: str | None
    manual_hw: bool
    manual_topic: str | None
    schedule_id: str | None
    updated_at: str  # ISO


class _RingBuffer:
    def __init__(self, maxlen: int = 1000):
        self.maxlen = maxlen
        self._buf: list[Event] = []
        self._lock = threading.Lock()

    def append(self, ev: Event) -> None:
        with self._lock:
            self._buf.append(ev)
            if len(self._buf) > self.maxlen:
                self._buf = self._buf[-self.maxlen :]

    def since(self, last_id: int) -> list[Event]:
        with self._lock:
            return [e for e in self._buf if e.id > last_id]


class SseClient:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        topics: set[str] | None = None,
        prefix: str | None = None,
        flush_interval_ms: int = 150,
        heartbeat_s: int = 15,
    ):
        self.loop = loop
        self.topics = topics
        self.prefix = prefix
        self.flush_interval_ms = flush_interval_ms
        self.heartbeat_s = heartbeat_s

        self._q: asyncio.Queue[str] = asyncio.Queue(maxsize=2000)  # готовые SSE-строки

        self._pending: dict[str, Change] = {}
        self._pending_ui: dict[str, UiStateChange] = {}

        self._last_send = 0.0
        self._last_ping = 0.0
        self._closed = False

    def matches(self, topic: str) -> bool:
        if self.topics is not None:
            return topic in self.topics
        if self.prefix is not None:
            return topic.startswith(self.prefix)
        return False

    def close(self) -> None:
        self._closed = True

    def push_change(self, ch: Change) -> None:
        # вызывается из thread-safe контекста (через loop.call_soon_threadsafe)
        if self._closed:
            return
        if not self.matches(ch.topic):
            return
        self._pending[ch.topic] = ch

    def push_ui_state(self, ch: UiStateChange) -> None:
        if self._closed:
            return
        # ui_state НЕ фильтруем по topic
        self._pending_ui[ch.ui_id] = ch

    async def drain(self) -> str:
        return await self._q.get()

    async def _emit(self, s: str) -> None:
        # если очередь забита — будем дропать самые старые (soft)
        if self._q.full():
            try:
                _ = self._q.get_nowait()
            except Exception:
                pass
        await self._q.put(s)

    async def tick(self, mk_event_id, ring: _RingBuffer) -> None:
        """
        Вызывается периодически из async таска (раз в ~50ms).
        Делает:
        - heartbeat
        - батчинг (не чаще flush_interval_ms)
        """
        if self._closed:
            return

        now = time.time()

        # heartbeat
        if now - self._last_ping >= self.heartbeat_s:
            self._last_ping = now
            await self._emit(": ping\n\n")

        # ---- UI STATE FLUSH ----
        if self._pending_ui and (now - self._last_send) * 1000.0 >= self.flush_interval_ms:
            ui_changes = list(self._pending_ui.values())
            self._pending_ui.clear()
            self._last_send = now

            ev_id = mk_event_id()
            payload = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
                "states": [
                    {
                        "ui_id": c.ui_id,
                        "mode_effective": c.mode_effective,
                        "mode_requested": c.mode_requested,
                        "manual_hw": c.manual_hw,
                        "manual_topic": c.manual_topic,
                        "schedule_id": c.schedule_id,
                        "updated_at": c.updated_at,
                    }
                    for c in ui_changes
                ],
            }

            data = json.dumps(payload, ensure_ascii=False)
            sse = f"event: ui_state\nid: {ev_id}\ndata: {data}\n\n"
            await self._emit(sse)

        # flush
        if not self._pending:
            return

        if (now - self._last_send) * 1000.0 < self.flush_interval_ms:
            return

        # формируем batched changes
        changes = list(self._pending.values())
        self._pending.clear()
        self._last_send = now

        ev_id = mk_event_id()
        ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"

        payload = {
            "ts": ts_iso,
            "changes": [
                {
                    "topic": c.topic,
                    "value_num": c.value_num,
                    "value_text": c.value_text,
                    "status_code": c.status_code,
                    "updated_at": c.updated_at,
                }
                for c in changes
            ],
        }

        ev = Event(
            id=ev_id,
            ts=ts_iso,
            changes=changes,
        )
        ring.append(ev)

        data = json.dumps(payload, ensure_ascii=False)
        sse = f"event: reading\nid: {ev_id}\ndata: {data}\n\n"
        await self._emit(sse)


class SseHub:
    def __init__(self):
        self._clients: set[SseClient] = set()
        self._lock = threading.Lock()

        self._event_id = 0
        self._event_id_lock = threading.Lock()
        self._ring = _RingBuffer(maxlen=2000)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._ticker_task: asyncio.Task | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _next_event_id(self) -> int:
        with self._event_id_lock:
            self._event_id += 1
            return self._event_id

    def active_connections(self) -> int:
        with self._lock:
            return len(self._clients)

    def start_ticker_if_needed(self) -> None:
        if self._loop is None:
            return
        if self._ticker_task is None or self._ticker_task.done():
            self._ticker_task = self._loop.create_task(self._ticker())

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            # snapshot clients
            with self._lock:
                clients = list(self._clients)
            # tick all
            for c in clients:
                try:
                    await c.tick(self._next_event_id, self._ring)
                except Exception:
                    # не падаем из-за одного клиента
                    pass

    def connect(
        self,
        loop: asyncio.AbstractEventLoop,
        topics: set[str] | None,
        prefix: str | None,
        last_event_id: Optional[int],
        flush_interval_ms: int = 150,
        heartbeat_s: int = 15,
    ) -> SseClient:
        if self._loop is None:
            self.set_loop(loop)
        self.start_ticker_if_needed()

        client = SseClient(
            loop=loop,
            topics=topics,
            prefix=prefix,
            flush_interval_ms=flush_interval_ms,
            heartbeat_s=heartbeat_s,
        )
        with self._lock:
            self._clients.add(client)
            active_sse_connections.set(len(self._clients))

        # best-effort replay
        if last_event_id is not None and self._loop is not None:
            missed = self._ring.since(last_event_id)
            if missed:
                async def _replay():
                    for ev in missed:
                        payload = {
                            "ts": ev.ts,
                            "changes": [
                                {
                                    "topic": c.topic,
                                    "value_num": c.value_num,
                                    "value_text": c.value_text,
                                    "status_code": c.status_code,
                                    "updated_at": c.updated_at,
                                }
                                for c in ev.changes
                            ],
                        }
                        data = json.dumps(payload, ensure_ascii=False)
                        sse = f"event: reading\nid: {ev.id}\ndata: {data}\n\n"
                        await client._emit(sse)

                self._loop.call_soon_threadsafe(lambda: asyncio.create_task(_replay()))

        return client

    def disconnect(self, client: SseClient) -> None:
        client.close()
        with self._lock:
            self._clients.discard(client)
            active_sse_connections.set(len(self._clients))

    def publish_change_threadsafe(self, ch: Change) -> None:
        """
        Вызывается из thread ingest. Мы пробрасываем обновление в event loop.
        """
        if self._loop is None:
            return

        def _push():
            with self._lock:
                clients = list(self._clients)
            for c in clients:
                c.push_change(ch)

        self._loop.call_soon_threadsafe(_push)

    def publish_ui_state_threadsafe(self, ch: UiStateChange) -> None:
        if self._loop is None:
            return

        def _push():
            with self._lock:
                clients = list(self._clients)
            for c in clients:
                c.push_ui_state(ch)

        self._loop.call_soon_threadsafe(_push)


hub = SseHub()
