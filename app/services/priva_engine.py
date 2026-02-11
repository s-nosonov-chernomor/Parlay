# app/services/priva_engine.py
from __future__ import annotations

import logging
import threading
import time

from app.db.session import SessionLocal
from app.db import priva_crud
from app.main_runtime import get_command_service
from app.services.command_service import CommandRequest

from app.metrics_priva import (
    priva_ticks_total,
    priva_elements_total,
    priva_commands_sent_total,
    priva_commands_skipped_total,
    priva_errors_total,
)

logger = logging.getLogger("priva")


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

    # 🔧 важное: "0.0", "1.0", "0,0"
    try:
        f = float(s.replace(",", "."))
        return 0 if f == 0.0 else 1
    except Exception:
        return None

def _coerce_for_send(value_type: str | None, src_num: float | None, src_txt: str | None):
    vt = (value_type or "").strip().lower()

    # 1) если это bool/int — всегда отправляем int 0/1
    if vt in {"bool", "boolean", "int", "int01", "u8", "u16", "u32"}:
        bit = _as_int01(src_num, src_txt)
        if bit is not None:
            return int(bit)

        # если пришло число 0.0/1.0, но _as_int01 не распознал
        if src_num is not None:
            return int(0 if float(src_num) == 0.0 else 1)

        # если пришёл текст "0"/"1"
        if src_txt is not None:
            s = str(src_txt).strip()
            if s.isdigit():
                return int(s)

        return None

    # 2) если float — оставляем float
    if vt in {"float", "double", "number"}:
        if src_num is not None:
            return float(src_num)
        if src_txt is not None:
            try:
                return float(str(src_txt).strip().replace(",", "."))
            except Exception:
                return str(src_txt)
        return None

    # 3) по умолчанию: если src_num целое — отправим int (это удобно для persay),
    # иначе float/строка как есть
    if src_num is not None:
        f = float(src_num)
        if abs(f - round(f)) < 1e-9:
            return int(round(f))
        return f

    return src_txt


def _values_equal(a_num, a_txt, b_num, b_txt, eps: float = 1e-6) -> bool:
    # если у источника число — сравниваем численно
    if b_num is not None:
        if a_num is None:
            return False
        return abs(float(a_num) - float(b_num)) <= eps

    # иначе текст
    a = "" if a_txt is None else str(a_txt)
    b = "" if b_txt is None else str(b_txt)
    return a == b

def _norm_for_compare(num: float | None, txt: str | None):
    """
    Нормализуем значения, чтобы "1" == 1.0 == true и т.п.
    Возвращает ("bool01", int) | ("num", float) | ("text", str) | ("none", None)
    """
    b = _as_int01(num, txt)
    if b is not None:
        return ("bool01", b)

    if num is not None:
        return ("num", float(num))

    if txt is None:
        return ("none", None)

    s = str(txt).strip()
    # если это число в тексте — сравним как число
    try:
        f = float(s.replace(",", "."))
        return ("num", f)
    except Exception:
        return ("text", s)


def _values_equal2(a_num, a_txt, b_num, b_txt, eps: float = 1e-6) -> bool:
    ka, va = _norm_for_compare(a_num, a_txt)
    kb, vb = _norm_for_compare(b_num, b_txt)

    # none != anything
    if ka == "none" or kb == "none":
        return ka == kb

    # bool01 сравниваем как bool01 даже если второй был "1.0"
    if ka == "bool01" or kb == "bool01":
        if ka != "bool01" or kb != "bool01":
            return False
        return int(va) == int(vb)

    # числовые
    if ka == "num" and kb == "num":
        return abs(float(va) - float(vb)) <= eps

    # текстовые
    if ka == "text" and kb == "text":
        return str(va) == str(vb)

    # разные типы считаем разными (чтобы не было сюрпризов)
    return False


class PrivaEngine:
    """
    PRIVA engine:
    - берёт ui_id в PRIVA
    - по ui_priva_bindings читает priva_topic
    - по ui_bindings (mqtt) пишет target topic
    - если HW-block => не управляет
    """
    def __init__(self, tick_s: float = 1.0, max_commands_per_tick: int = 5000):
        self.tick_s = float(tick_s)
        self.max_commands_per_tick = int(max_commands_per_tick)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._cooldown_s = 5.0 # долбим persay каждые Х чтобы не часто, но и чтобы не отдыхал
        self._last_sent_at: dict[tuple[str, str], float] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="priva-engine", daemon=True)
        self._thread.start()
        logger.info("PrivaEngine started tick_s=%s", self.tick_s)

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
                priva_errors_total.inc()
                logger.exception("PRIVA tick failed")
            dt = time.time() - t0
            sleep_for = max(0.0, self.tick_s - dt)
            self._stop.wait(sleep_for)

    def tick(self):
        priva_ticks_total.inc()

        with SessionLocal() as session:
            ui_ids = priva_crud.list_priva_states(session)
            priva_elements_total.set(len(ui_ids))
            if not ui_ids:
                return

            mqtt_by_ui = priva_crud.load_mqtt_bindings(session, ui_ids)     # ui -> bind_key -> mqtt binding
            priva_by_ui = priva_crud.load_priva_bindings(session, ui_ids)   # ui -> bind_key -> priva binding
            manual_topic_by_ui = priva_crud.load_manual_topics(session, ui_ids)

            # собрать все topics для чтения last
            topics_to_read: set[str] = set()

            # priva topics + mqtt topics
            for ui_id in ui_ids:
                for bind_key, pb in priva_by_ui.get(ui_id, {}).items():
                    topics_to_read.add(pb.priva_topic)
                    mb = mqtt_by_ui.get(ui_id, {}).get(bind_key)
                    if mb and mb.topic:
                        topics_to_read.add(mb.topic)

            # manual topics
            for t in manual_topic_by_ui.values():
                topics_to_read.add(t)

            last = priva_crud.load_last_values(session, topics_to_read)

            svc = get_command_service()
            sent = 0
            skipped = 0

            for ui_id in ui_ids:
                if sent >= self.max_commands_per_tick:
                    break

                # HW block
                manual_topic = manual_topic_by_ui.get(ui_id)
                if manual_topic:
                    vnum, vtxt = last.get(manual_topic, (None, None))
                    bit = _as_int01(vnum, vtxt)
                    if bit is not None and bit == 0:
                        skipped += 1
                        continue

                pb_map = priva_by_ui.get(ui_id, {})
                if not pb_map:
                    skipped += 1
                    continue

                for bind_key, pb in pb_map.items():
                    if sent >= self.max_commands_per_tick:
                        break

                    mb = mqtt_by_ui.get(ui_id, {}).get(bind_key)
                    if not mb or not mb.topic:
                        skipped += 1
                        continue

                    src_num, src_txt = last.get(pb.priva_topic, (None, None))
                    dst_num, dst_txt = last.get(mb.topic, (None, None))

                    # если по источнику вообще нет данных — пропускаем
                    if src_num is None and src_txt is None:
                        skipped += 1
                        continue

                    if _values_equal2(dst_num, dst_txt, src_num, src_txt):
                        skipped += 1
                        continue

                    now = time.time()
                    cd_key = (ui_id, bind_key)
                    last_sent = self._last_sent_at.get(cd_key, 0.0)
                    if (now - last_sent) < self._cooldown_s:
                        skipped += 1
                        continue

                    value_obj = _coerce_for_send(mb.value_type, src_num, src_txt)
                    if value_obj is None:
                        skipped += 1
                        continue

                    svc.send(
                        session,
                        CommandRequest(
                            topic=mb.topic,
                            value=value_obj,
                            as_json=True,
                            requested_by="priva",
                            correlation_id=pb.priva_topic,
                        ),
                    )
                    self._last_sent_at[cd_key] = now
                    sent += 1

            session.commit()

            priva_commands_sent_total.inc(sent)
            priva_commands_skipped_total.inc(skipped)

            if sent:
                logger.info("PRIVA tick: sent=%s skipped=%s elements=%s", sent, skipped, len(ui_ids))
