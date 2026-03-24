# app/services/par_dli_engine.py
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.db import par_dli_crud
from app.main_runtime import get_command_service
from app.services.command_service import CommandRequest
from app.services.bind_resolver import resolve_binding_topic

from app.metrics_par_dli import (
    par_dli_ticks_total,
    par_dli_elements_total,
    par_dli_commands_sent_total,
    par_dli_commands_skipped_total,
    par_dli_errors_total,
)

logger = logging.getLogger("par_dli")


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
    try:
        f = float(s.replace(",", "."))
        return 0 if f == 0.0 else 1
    except Exception:
        return None


def _coerce_float(value_num: float | None, value_text: str | None) -> float | None:
    if value_num is not None:
        return float(value_num)
    if value_text is None:
        return None
    try:
        return float(str(value_text).strip().replace(",", "."))
    except Exception:
        return None


def _compute_pwm_pct(par_top: float, ppfd_setpoint_umol: float, fixture_umol_100: float) -> float:
    required_from_lamps = ppfd_setpoint_umol - par_top
    if required_from_lamps <= 0:
        return 0.0
    if required_from_lamps >= fixture_umol_100:
        return 100.0
    return max(0.0, min(100.0, required_from_lamps / fixture_umol_100 * 100.0))


def _is_after_or_equal(now_t: dtime, border_t: dtime) -> bool:
    return now_t >= border_t


def _time_in_window(now_t: dtime, start_t: dtime, end_t: dtime) -> bool:
    if start_t <= end_t:
        return start_t <= now_t <= end_t
    return now_t >= start_t or now_t <= end_t


class ParDliEngine:
    """
    PAR_DLI engine (new architecture):
    - сценарии живут отдельно по par_id
    - линии ссылаются на сценарий через ui_element_state.par_id
    - DLI считаем по истории с начала суток и только в периоды enabled=1
    - PWM считаем по текущему верхнему PAR
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

        # cooldown per scenario (par_id)
        self._last_run_by_par: dict[str, float] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="par-dli-engine", daemon=True)
        self._thread.start()
        logger.info("ParDliEngine started tick_s=%s tz=%s", self.tick_s, self.tz_default)

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
                par_dli_errors_total.inc()
                logger.exception("PAR_DLI tick failed")
            dt = time.time() - t0
            self._stop.wait(max(0.0, self.tick_s - dt))

    def tick(self):
        par_dli_ticks_total.inc()

        with SessionLocal() as session:
            configs = par_dli_crud.list_configs(session)
            if not configs:
                par_dli_elements_total.set(0)
                return

            svc = get_command_service()

            sent = 0
            skipped = 0
            total_ui = 0

            for cfg in configs:
                par_id = cfg["par_id"]

                # scenario cooldown
                now_mon = time.time()
                last_run = self._last_run_by_par.get(par_id, 0.0)
                if (now_mon - last_run) < float(cfg["correction_interval_s"]):
                    skipped += 1
                    continue

                ui_ids = par_dli_crud.list_ui_for_par(session, par_id)
                total_ui += len(ui_ids)

                if not ui_ids:
                    self._last_run_by_par[par_id] = now_mon
                    continue

                tz_name = (cfg.get("tz") or self.tz_default).strip() or self.tz_default
                tz = ZoneInfo(tz_name)
                now_local = datetime.now(tz)
                now_utc = datetime.now(timezone.utc)
                now_t = now_local.timetz().replace(tzinfo=None)
                day_start_utc = par_dli_crud.local_day_start_utc(now_local)

                for ui_id in ui_ids:
                    if sent >= self.max_commands_per_tick:
                        break

                    # HW block
                    manual_topic = par_dli_crud.load_manual_topic(session, ui_id)
                    if manual_topic:
                        mvnum, mvtxt, _mts = par_dli_crud.load_last_values(session, [manual_topic]).get(
                            manual_topic, (None, None, None)
                        )
                        bit = _as_int01(mvnum, mvtxt)
                        if bit is not None and bit == 0:
                            skipped += 1
                            continue

                    # resolve required topics
                    par_top_topic = resolve_binding_topic(session, ui_id, cfg["par_top_bind_key"])
                    par_sum_topic = resolve_binding_topic(session, ui_id, cfg["par_sum_bind_key"])

                    enabled_topics = [
                        topic
                        for topic in (
                            resolve_binding_topic(session, ui_id, bk)
                            for bk in cfg["enabled_bind_keys"]
                        )
                        if topic
                    ]
                    dim_topics = [
                        topic
                        for topic in (
                            resolve_binding_topic(session, ui_id, bk)
                            for bk in cfg["dim_bind_keys"]
                        )
                        if topic
                    ]

                    if not par_top_topic or not par_sum_topic or not enabled_topics or not dim_topics:
                        skipped += 1
                        continue

                    topics_for_last = [par_top_topic, par_sum_topic] + enabled_topics + dim_topics
                    last_map = par_dli_crud.load_last_values(session, topics_for_last)

                    # current par_top
                    par_top_num, par_top_txt, _ = last_map.get(par_top_topic, (None, None, None))
                    par_top = max(0.0, _coerce_float(par_top_num, par_top_txt) or 0.0)

                    # current actual enabled (any channel)
                    current_enabled = False
                    for topic in enabled_topics:
                        vnum, vtxt, _ = last_map.get(topic, (None, None, None))
                        bit = _as_int01(vnum, vtxt)
                        if bit == 1:
                            current_enabled = True
                            break

                    # representative current dim = first available dim
                    current_dim = None
                    for topic in dim_topics:
                        vnum, vtxt, _ = last_map.get(topic, (None, None, None))
                        val = _coerce_float(vnum, vtxt)
                        if val is not None:
                            current_dim = float(val)
                            break

                    # ------------------------------------------------
                    # 1) DLI by history, only while enabled=1
                    # ------------------------------------------------
                    dli_raw, dli_capped = par_dli_crud.calc_dli_for_line(
                        session=session,
                        par_sum_topic=par_sum_topic,
                        enabled_topics=enabled_topics,
                        start_ts=day_start_utc,
                        end_ts=now_utc,
                        cap_umol=cfg["dli_cap_umol"],
                    )

                    current_dli = dli_capped if cfg["use_dli_cap"] else dli_raw
                    target_reached = current_dli >= float(cfg["dli_target_mol"])

                    # ------------------------------------------------
                    # 2) enabled decision
                    # ------------------------------------------------
                    desired_enabled = 1

                    if now_t < cfg["start_time"]:
                        desired_enabled = 0
                    elif _is_after_or_equal(now_t, cfg["off_window_end"]):
                        desired_enabled = 0
                    elif _time_in_window(now_t, cfg["off_window_start"], cfg["off_window_end"]) and target_reached:
                        desired_enabled = 0

                    # ------------------------------------------------
                    # 3) pwm decision
                    # ------------------------------------------------
                    desired_pwm = _compute_pwm_pct(
                        par_top=par_top,
                        ppfd_setpoint_umol=float(cfg["ppfd_setpoint_umol"]),
                        fixture_umol_100=float(cfg["fixture_umol_100"]),
                    )

                    if desired_enabled == 0:
                        desired_pwm = 0.0

                    deadband_pwm = (
                        float(cfg["par_deadband_umol"]) / float(cfg["fixture_umol_100"])
                    ) * 100.0

                    # ------------------------------------------------
                    # 4) send enabled commands if needed
                    # ------------------------------------------------
                    if bool(current_enabled) != bool(desired_enabled):
                        for topic in enabled_topics:
                            svc.send(
                                session,
                                CommandRequest(
                                    topic=topic,
                                    value=int(desired_enabled),
                                    as_json=True,
                                    requested_by="par_dli",
                                    correlation_id=par_id,
                                ),
                            )
                            sent += 1
                    else:
                        skipped += 1

                    # ------------------------------------------------
                    # 5) send dim commands if needed
                    # ------------------------------------------------
                    if current_dim is None or abs(float(current_dim) - float(desired_pwm)) >= deadband_pwm:
                        for topic in dim_topics:
                            svc.send(
                                session,
                                CommandRequest(
                                    topic=topic,
                                    value=round(float(desired_pwm), 3),
                                    as_json=True,
                                    requested_by="par_dli",
                                    correlation_id=par_id,
                                ),
                            )
                            sent += 1
                    else:
                        skipped += 1

                self._last_run_by_par[par_id] = now_mon

            session.commit()

            par_dli_elements_total.set(total_ui)
            par_dli_commands_sent_total.inc(sent)
            par_dli_commands_skipped_total.inc(skipped)

            if sent:
                logger.info("PAR_DLI tick: sent=%s skipped=%s elements=%s", sent, skipped, total_ui)