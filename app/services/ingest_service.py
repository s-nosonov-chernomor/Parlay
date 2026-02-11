# app/services/ingest_service.py

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from queue import Queue, Full, Empty

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db import crud
from app.mqtt.parser import parse_mqtt_payload, ParsedMessage

from app.settings import get_settings
settings = get_settings()

from app.sse.hub import hub, Change
from sqlalchemy import select
from app.db.models_ui import UiHwSource, UiHwMember, UiElementState
from app.sse.hub import UiStateChange

from app.metrics import (
    mqtt_messages_total,
    readings_processed_total,
    ingest_dropped_total,
    ingest_queue_size,
)
from app.metrics import db_flush_errors_total, ingest_batch_size_last

logger = logging.getLogger("ingest")


class _ParamCache:
    """
    Простой LRU кэш topic -> parameter_id.
    """
    def __init__(self, max_size: int):
        self.max_size = max_size
        self._d: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> int | None:
        with self._lock:
            v = self._d.get(key)
            if v is None:
                return None
            self._d.move_to_end(key)
            return v

    def put(self, key: str, value: int):
        with self._lock:
            if key in self._d:
                self._d[key] = value
                self._d.move_to_end(key)
                return
            self._d[key] = value
            if len(self._d) > self.max_size:
                self._d.popitem(last=False)


class IngestService:
    def __init__(self):
        self.queue: Queue[tuple[str, bytes]] = Queue(maxsize=settings.ingest_queue_max)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._cache = _ParamCache(settings.param_cache_size)

        self._dropped = 0
        self._processed = 0

    def push(self, topic: str, payload: bytes):
        mqtt_messages_total.inc()
        try:
            self.queue.put_nowait((topic, payload))
            ingest_queue_size.set(self.queue.qsize())
        except Full:
            self._dropped += 1
            ingest_dropped_total.inc()
            # не спамим логом на каждый дроп
            if self._dropped % 1000 == 0:
                logger.warning("Ingest queue FULL. dropped=%s", self._dropped)

    def start(self):
        self._thread = threading.Thread(target=self._run, name="ingest-worker", daemon=True)
        self._thread.start()
        logger.info("IngestService started")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _resolve_parameter_id(self, session: Session, topic: str) -> int:
        pid = self._cache.get(topic)
        if pid is not None:
            return pid
        pid = crud.upsert_parameter(session, topic)
        self._cache.put(topic, pid)
        return pid

    def _run(self):
        batch: list[tuple[str, bytes]] = []
        last_flush = time.time()

        while not self._stop.is_set():
            timeout = max(0.01, settings.db_flush_interval_ms / 1000)
            try:
                item = self.queue.get(timeout=timeout)
                batch.append(item)
            except Empty:
                pass

            now = time.time()
            if batch and (len(batch) >= settings.db_batch_size or (now - last_flush) >= (settings.db_flush_interval_ms / 1000)):
                self._flush(batch)
                batch.clear()
                last_flush = now

        # финальный flush
        if batch:
            self._flush(batch)

    def _flush(self, batch: list[tuple[str, bytes]]):
        try:
            with SessionLocal() as session:
                rows: list[crud.ReadingRow] = []

                for topic, payload in batch:
                    pm: ParsedMessage = parse_mqtt_payload(topic, payload)
                    pid = self._resolve_parameter_id(session, pm.topic)

                    raw_to_store = pm.raw if settings.store_raw else None

                    rows.append(
                        crud.ReadingRow(
                            topic=pm.topic,
                            parameter_id=pid,
                            ts=pm.ts,
                            trigger=pm.trigger,
                            status_source=pm.status_source,
                            status_code=pm.status_code,
                            status_message=pm.status_message,
                            silent_for_s=pm.silent_for_s,
                            value_num=pm.value_num,
                            value_text=pm.value_text,
                            raw=raw_to_store,
                        )
                    )

                crud.insert_readings(session, rows)
                crud.upsert_last(session, rows)
                session.commit()

                ingest_batch_size_last.set(len(batch))
                readings_processed_total.inc(len(batch))
                ingest_queue_size.set(self.queue.qsize())

                # app/services/ingest_service.py (в _flush после commit)
                try:
                    for r in crud.latest_per_topic(rows):
                        # dedup тут можно не делать — hub сам дедупит в батче по topic
                        hub.publish_change_threadsafe(
                            Change(
                                topic=r.topic,
                                ts=r.ts.isoformat(),
                                value_num=r.value_num,
                                value_text=r.value_text,
                                status_code=r.status_code,
                                updated_at=r.ts.isoformat(),
                            )
                        )
                except Exception:
                    logger.exception("SSE publish failed (ignored).")

                # ---- UI state SSE on manual_topic changes ----
                try:
                    latest = list(crud.latest_per_topic(rows))
                    changed_topics = {r.topic for r in latest}

                    # какие изменившиеся topics являются manual_topic (из ui_hw_sources)
                    manual_topics = session.execute(
                        select(UiHwSource.manual_topic).where(UiHwSource.manual_topic.in_(changed_topics))
                    ).scalars().all()
                    manual_topics_set = {t for t in manual_topics if t}

                    if manual_topics_set:
                        # manual_topic -> ui_id
                        mt_rows = session.execute(
                            select(UiHwMember.ui_id, UiHwSource.manual_topic)
                            .select_from(UiHwMember)
                            .join(UiHwSource, UiHwSource.source_id == UiHwMember.source_id)
                            .where(UiHwSource.manual_topic.in_(manual_topics_set))
                        ).all()

                        affected_ui_ids = sorted({str(ui_id) for ui_id, _mt in mt_rows})
                        if affected_ui_ids:
                            # mode_requested / schedule_id
                            st_rows = session.execute(
                                select(UiElementState.ui_id, UiElementState.mode_requested, UiElementState.schedule_id)
                                .where(UiElementState.ui_id.in_(affected_ui_ids))
                            ).all()
                            st_map = {str(ui_id): (mode_req, sched_id) for ui_id, mode_req, sched_id in st_rows}

                            # manual_topic по ui_id
                            mt_by_ui_rows = session.execute(
                                select(UiHwMember.ui_id, UiHwSource.manual_topic)
                                .select_from(UiHwMember)
                                .join(UiHwSource, UiHwSource.source_id == UiHwMember.source_id)
                                .where(UiHwMember.ui_id.in_(affected_ui_ids))
                            ).all()
                            manual_topic_by_ui = {str(ui_id): (str(mt) if mt else None) for ui_id, mt in mt_by_ui_rows}

                            latest_map = {r.topic: r for r in latest}

                            def _as_int01(vnum, vtxt):
                                if vnum is not None:
                                    return 0 if float(vnum) == 0.0 else 1
                                if vtxt is None:
                                    return None
                                s = str(vtxt).strip().lower()
                                if s in {"0", "false", "off", "no"}:
                                    return 0
                                if s in {"1", "true", "on", "yes"}:
                                    return 1
                                return None

                            for ui_id in affected_ui_ids:
                                mt = manual_topic_by_ui.get(ui_id)
                                manual_hw = False

                                # значение manual_topic из текущего batch (самое свежее)
                                if mt and mt in latest_map:
                                    rr = latest_map[mt]
                                    bit = _as_int01(rr.value_num, rr.value_text)
                                    manual_hw = (bit is not None and bit == 0)
                                    updated_at = rr.ts.isoformat()
                                else:
                                    updated_at = datetime.now().isoformat()

                                mode_req, sched_id = st_map.get(ui_id, (None, None))
                                mode_effective = "MANUAL_HW" if manual_hw else (mode_req or "WEB")

                                hub.publish_ui_state_threadsafe(
                                    UiStateChange(
                                        ui_id=ui_id,
                                        mode_effective=mode_effective,
                                        mode_requested=mode_req,
                                        manual_hw=manual_hw,
                                        manual_topic=mt,
                                        schedule_id=sched_id,
                                        updated_at=updated_at,
                                    )
                                )
                except Exception:
                    logger.exception("SSE ui_state publish failed (ignored).")

                self._processed += len(batch)
                if self._processed % 5000 == 0:
                    logger.info("Processed=%s dropped=%s qsize=%s", self._processed, self._dropped, self.queue.qsize())

        except Exception:
            db_flush_errors_total.inc()
            logger.exception("DB flush failed (batch=%s). Will continue.", len(batch))
