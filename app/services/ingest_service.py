# app/services/ingest_service.py

from __future__ import annotations

import logging
import threading
import time
import psycopg
from sqlalchemy.exc import IntegrityError
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

    def delete(self, key: str):
        with self._lock:
            self._d.pop(key, None)

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
            db_pid = crud.get_parameter_id_by_topic(session, topic)
            if db_pid is not None:
                if db_pid != pid:
                    self._cache.put(topic, db_pid)
                    return db_pid
                return pid
            # если topic исчез из БД
            self._cache.delete(topic)

        pid = crud.get_parameter_id_by_topic(session, topic)
        if pid is not None:
            self._cache.put(topic, pid)
            return pid

        pid = crud.upsert_parameter(session, topic)
        self._cache.put(topic, pid)
        return pid

    def _is_missing_partition_error(self, exc: Exception) -> bool:
        s = str(exc).lower()
        return (
            "no partition of relation" in s
            or "для строки не найдена секция" in s
            or "no partition found for row" in s
        )

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
        rows: list[crud.ReadingRow] = []

        # 1) сначала парсим batch в rows один раз
        try:
            for topic, payload in batch:
                pm: ParsedMessage = parse_mqtt_payload(topic, payload)

                # parameter_id пока не знаем, он зависит от session
                rows.append(
                    crud.ReadingRow(
                        topic=pm.topic,
                        parameter_id=0,  # временно, назначим ниже
                        ts=pm.ts,
                        trigger=pm.trigger,
                        status_source=pm.status_source,
                        status_code=pm.status_code,
                        status_message=pm.status_message,
                        silent_for_s=pm.silent_for_s,
                        value_num=pm.value_num,
                        value_text=pm.value_text,
                        raw=(pm.raw if settings.store_raw else None),
                    )
                )
        except Exception:
            db_flush_errors_total.inc()
            logger.exception("MQTT parse failed (batch=%s). Will continue.", len(batch))
            return

        def _write_once(create_partition_if_needed: bool = False) -> None:
            with SessionLocal() as session:
                # 2) resolve parameter_id уже внутри текущей session
                for r in rows:
                    r.parameter_id = self._resolve_parameter_id(session, r.topic)

                if create_partition_if_needed and rows:
                    # создаём партиции по всем месяцам, которые встретились в batch
                    seen = set()
                    for r in rows:
                        key = (r.ts.year, r.ts.month)
                        if key in seen:
                            continue
                        seen.add(key)
                        crud.ensure_reading_partition_for_ts(session, r.ts)
                    session.commit()

                crud.insert_readings(session, rows)
                crud.upsert_last(session, rows)
                session.commit()

                ingest_batch_size_last.set(len(batch))
                readings_processed_total.inc(len(batch))
                ingest_queue_size.set(self.queue.qsize())

                try:
                    for r in crud.latest_per_topic(rows):
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

        # 3) пробуем обычную запись
        try:
            _write_once(create_partition_if_needed=False)

            self._processed += len(batch)
            if self._processed % 5000 == 0:
                logger.info("Processed=%s dropped=%s qsize=%s", self._processed, self._dropped, self.queue.qsize())

        except IntegrityError as e:
            if self._is_missing_partition_error(e):
                logger.warning("Missing reading partition detected. Creating partition(s) and retrying.")
                try:
                    _write_once(create_partition_if_needed=True)

                    self._processed += len(batch)
                    if self._processed % 5000 == 0:
                        logger.info("Processed=%s dropped=%s qsize=%s", self._processed, self._dropped, self.queue.qsize())
                    return
                except Exception:
                    db_flush_errors_total.inc()
                    logger.exception("Retry after partition creation failed (batch=%s).", len(batch))
                    return

            db_flush_errors_total.inc()
            logger.exception("DB flush failed (batch=%s). Will continue.", len(batch))

        except Exception:
            db_flush_errors_total.inc()
            logger.exception("DB flush failed (batch=%s). Will continue.", len(batch))

