# app/services/auto_engine.py
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.db import auto_crud
from app.main_runtime import get_command_service
from app.services.command_service import CommandRequest

from app.metrics_auto import (
    auto_ticks_total,
    auto_elements_total,
    auto_commands_sent_total,
    auto_commands_skipped_total,
    auto_errors_total,
)

logger = logging.getLogger("auto")


def _as_int01(value_num: float | None, value_text: str | None) -> int | None:
    if value_num is not None:
        return 0 if float(value_num) == 0.0 else 1
    if value_text is None:
        return None
    s = str(value_text).strip().lower()
    if s in {"0", "false", "off", "no"}:
        return 0
    if s in {"1", "true", "on", "yes"}:
        return 1
    return None


@dataclass(slots=True)
class TargetValue:
    value_num: float | None
    value_text: str | None


def _pick_target_for_now(events, now_t: dtime) -> TargetValue | None:
    """
    Выбираем "последнее событие <= now_t", иначе wrap-around (последнее за сутки).
    events: отсортированы по at_time ASC.
    """
    if not events:
        return None

    chosen = None
    for e in events:
        if e.at_time <= now_t:
            chosen = e
        else:
            break

    if chosen is None:
        chosen = events[-1]  # wrap-around: ночной режим до первого события

    return TargetValue(value_num=chosen.value_num, value_text=chosen.value_text)


def _equal_current_to_target(
    cur_num: float | None,
    cur_text: str | None,
    tgt: TargetValue,
    eps: float = 1e-6,
) -> bool:
    # числовая цель
    if tgt.value_num is not None:
        if cur_num is None:
            return False
        return abs(float(cur_num) - float(tgt.value_num)) <= eps

    # текстовая цель
    cur = "" if cur_text is None else str(cur_text)
    tgt_s = "" if tgt.value_text is None else str(tgt.value_text)
    return cur == tgt_s


class AutoEngine:
    """
    AUTO engine:
    - на каждом тике ищет ui_element_state.mode_requested == 'AUTO'
    - берёт schedule_id
    - вычисляет целевые значения по schedule_events
    - сравнивает с parameter_last по mqtt bindings
    - публикует команды через CommandService
    """
    def __init__(
        self,
        tick_s: float = 1.0,
        tz_default: str = "Europe/Riga",
        max_commands_per_tick: int = 5000,
    ):
        self.tick_s = float(tick_s)
        self.tz_default = tz_default
        self.max_commands_per_tick = int(max_commands_per_tick)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="auto-engine", daemon=True)
        self._thread.start()
        logger.info("AutoEngine started tick_s=%s tz=%s", self.tick_s, self.tz_default)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self):
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.tick()
            except Exception:
                auto_errors_total.inc()
                logger.exception("AUTO tick failed")
            dt = time.time() - t0
            sleep_for = max(0.0, self.tick_s - dt)
            self._stop.wait(sleep_for)

    def tick(self):
        auto_ticks_total.inc()

        with SessionLocal() as session:
            auto_states = auto_crud.list_auto_states(session)  # [(ui_id, schedule_id)]
            ui_ids = [ui_id for (ui_id, _sid) in auto_states]
            schedule_ids = [sid for (_ui, sid) in auto_states]

            auto_elements_total.set(len(ui_ids))
            if not auto_states:
                return

            bindings_by_ui = auto_crud.load_mqtt_bindings(session, ui_ids)
            schedule_events = auto_crud.load_schedule_events(session, schedule_ids)

            manual_topic_by_ui = auto_crud.load_manual_topics(session, ui_ids)

            # все topics, которые нужно прочитать из parameter_last
            topics_to_read: set[str] = set()

            # управляемые mqtt topics
            for ui_id in ui_ids:
                for b in bindings_by_ui.get(ui_id, []):
                    if b.topic:
                        topics_to_read.add(b.topic)

            # manual topics
            for t in manual_topic_by_ui.values():
                topics_to_read.add(t)

            last_by_topic = auto_crud.load_last_values(session, topics_to_read)

            now = datetime.now(ZoneInfo(self.tz_default))
            now_t = now.timetz().replace(tzinfo=None)

            svc = get_command_service()

            sent = 0
            skipped = 0

            for ui_id, schedule_id in auto_states:
                if sent >= self.max_commands_per_tick:
                    break

                # 1) аппаратный блок
                manual_topic = manual_topic_by_ui.get(ui_id)
                if manual_topic:
                    vnum, vtxt = last_by_topic.get(manual_topic, (None, None))
                    bit = _as_int01(vnum, vtxt)
                    if bit is not None and bit == 0:
                        skipped += 1
                        continue

                # 2) события расписания (bind_key -> list[events])
                ev_by_bind = schedule_events.get(schedule_id)
                if not ev_by_bind:
                    skipped += 1
                    continue

                # 3) mqtt bindings UI (управлять только тем, что есть в расписании)
                for b in bindings_by_ui.get(ui_id, []):
                    if sent >= self.max_commands_per_tick:
                        break
                    if not b.topic:
                        continue

                    events_for_bind = ev_by_bind.get(b.bind_key)
                    if not events_for_bind:
                        continue  # bind_key нет в расписании => оставляем как есть

                    tgt = _pick_target_for_now(events_for_bind, now_t)
                    if tgt is None:
                        continue

                    cur_num, cur_text = last_by_topic.get(b.topic, (None, None))
                    if _equal_current_to_target(cur_num, cur_text, tgt):
                        skipped += 1
                        continue

                    value_obj = tgt.value_num if tgt.value_num is not None else tgt.value_text

                    svc.send(
                        session,
                        CommandRequest(
                            topic=b.topic,
                            value=value_obj,
                            as_json=True,
                            requested_by="auto",
                            correlation_id=schedule_id,
                        ),
                    )
                    sent += 1

            session.commit()

            auto_commands_sent_total.inc(sent)
            auto_commands_skipped_total.inc(skipped)

            if sent:
                logger.info("AUTO tick: sent=%s skipped=%s elements=%s", sent, skipped, len(ui_ids))
