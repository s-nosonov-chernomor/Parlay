# app/services/par_dli_engine.py

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone, time as dtime, timedelta
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.db import par_dli_crud
from app.main_runtime import get_command_service
from app.services.command_service import CommandRequest

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


def _time_in_window(now_t: dtime, start_t: dtime, end_t: dtime) -> bool:
    if start_t <= end_t:
        return start_t <= now_t <= end_t
    return now_t >= start_t or now_t <= end_t


def _is_after_or_equal(now_t: dtime, border_t: dtime) -> bool:
    return now_t >= border_t


def _compute_pwm_pct(par_top: float, par_target: float, fixture_umol_100: float) -> float:
    required_from_lamps = par_target - par_top
    if required_from_lamps <= 0:
        return 0.0
    if required_from_lamps >= fixture_umol_100:
        return 100.0
    return max(0.0, min(100.0, required_from_lamps / fixture_umol_100 * 100.0))

def _local_day_start_utc(now_local: datetime) -> datetime:
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)

@dataclass(slots=True)
class SendDecision:
    enabled: int
    pwm_pct: float


class ParDliEngine:
    """
    PAR_DLI engine:
    - регулирует dim по верхнему PAR датчику
    - считает DLI по нижнему суммарному PAR датчику
    - отключает по окну off_window и достижению DLI
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

    def _send_if_needed(
        self,
        session,
        svc,
        ui_id: str,
        enabled_topic: str,
        dim_topic: str,
        decision: SendDecision,
        cur_enabled_num: float | None,
        cur_enabled_txt: str | None,
        cur_dim_num: float | None,
        cur_dim_txt: str | None,
    ) -> int:
        sent = 0

        cur_enabled = _as_int01(cur_enabled_num, cur_enabled_txt)
        cur_dim = _coerce_float(cur_dim_num, cur_dim_txt)
        target_pwm_rounded = round(float(decision.pwm_pct), 3)

        if cur_enabled != decision.enabled:
            svc.send(
                session,
                CommandRequest(
                    topic=enabled_topic,
                    value=int(decision.enabled),
                    as_json=True,
                    requested_by="par_dli",
                    correlation_id=ui_id,
                ),
            )
            sent += 1

        if cur_dim is None or abs(float(cur_dim) - target_pwm_rounded) > 1e-6:
            svc.send(
                session,
                CommandRequest(
                    topic=dim_topic,
                    value=target_pwm_rounded,
                    as_json=True,
                    requested_by="par_dli",
                    correlation_id=ui_id,
                ),
            )
            sent += 1

        return sent

    def tick(self):
        par_dli_ticks_total.inc()

        with SessionLocal() as session:
            ui_ids = par_dli_crud.list_par_dli_states(session)
            par_dli_elements_total.set(len(ui_ids))
            if not ui_ids:
                return

            svc = get_command_service()

            sent = 0
            skipped = 0

            for ui_id in ui_ids:
                if sent >= self.max_commands_per_tick:
                    break

                cfg = par_dli_crud.load_config(session, ui_id)
                if not cfg:
                    skipped += 1
                    continue

                tz_name = (cfg.tz or self.tz_default).strip() or self.tz_default
                tz = ZoneInfo(tz_name)
                now_local = datetime.now(tz)
                now_utc = datetime.now(timezone.utc)
                now_t = now_local.timetz().replace(tzinfo=None)
                today_local = now_local.date()

                st = par_dli_crud.load_state(session, ui_id)
                is_new_day_state = False
                if st is None or st.local_date != today_local:
                    st = par_dli_crud.reset_state_for_day(session, ui_id, today_local)
                    is_new_day_state = True

                bind_map = par_dli_crud.load_mqtt_bindings(
                    session,
                    ui_id,
                    [
                        cfg.par_top_bind_key,
                        cfg.par_sum_bind_key,
                        cfg.enabled_bind_key,
                        cfg.dim_bind_key,
                    ],
                )

                if (
                    cfg.par_top_bind_key not in bind_map
                    or cfg.par_sum_bind_key not in bind_map
                    or cfg.enabled_bind_key not in bind_map
                    or cfg.dim_bind_key not in bind_map
                ):
                    skipped += 1
                    continue

                manual_topic = par_dli_crud.load_manual_topic(session, ui_id)

                topics = [
                    bind_map[cfg.par_top_bind_key].topic,
                    bind_map[cfg.par_sum_bind_key].topic,
                    bind_map[cfg.enabled_bind_key].topic,
                    bind_map[cfg.dim_bind_key].topic,
                ]
                if manual_topic:
                    topics.append(manual_topic)

                last = par_dli_crud.load_last_values(session, topics)

                # HW block
                if manual_topic:
                    mvnum, mvtxt, _mts = last.get(manual_topic, (None, None, None))
                    bit = _as_int01(mvnum, mvtxt)
                    if bit is not None and bit == 0:
                        skipped += 1
                        continue

                par_top_topic = bind_map[cfg.par_top_bind_key].topic
                par_sum_topic = bind_map[cfg.par_sum_bind_key].topic
                enabled_topic = bind_map[cfg.enabled_bind_key].topic
                dim_topic = bind_map[cfg.dim_bind_key].topic

                par_top_num, par_top_txt, _ = last.get(par_top_topic, (None, None, None))
                par_sum_num, par_sum_txt, _ = last.get(par_sum_topic, (None, None, None))
                cur_enabled_num, cur_enabled_txt, _ = last.get(enabled_topic, (None, None, None))
                cur_dim_num, cur_dim_txt, _ = last.get(dim_topic, (None, None, None))

                par_top = max(0.0, _coerce_float(par_top_num, par_top_txt) or 0.0)
                par_sum = max(0.0, _coerce_float(par_sum_num, par_sum_txt) or 0.0)

                # ------------------------------------------------
                # 1) DLI integrate from sum sensor
                # ------------------------------------------------
                if st.last_calc_ts is None:
                    # recovery after restart / first run during the day:
                    # restore accumulated DLI from local midnight up to now
                    day_start_utc = _local_day_start_utc(now_local)

                    if now_utc > day_start_utc:
                        raw_mol, capped_mol = par_dli_crud.calc_dli_from_history(
                            session=session,
                            topic=par_sum_topic,
                            start_ts=day_start_utc,
                            end_ts=now_utc,
                            cap_umol=cfg.par_target_umol,
                        )
                        st.dli_raw_mol = float(raw_mol)
                        st.dli_capped_mol = float(capped_mol)

                    st.last_calc_ts = now_utc
                    st.last_sum_par_umol = par_sum
                else:
                    dt_s = max(0.0, (now_utc - st.last_calc_ts).total_seconds())
                    if dt_s > 0:
                        prev_sum = float(st.last_sum_par_umol if st.last_sum_par_umol is not None else par_sum)
                        st.dli_raw_mol += prev_sum * dt_s / 1_000_000.0
                        st.dli_capped_mol += min(prev_sum, cfg.par_target_umol) * dt_s / 1_000_000.0
                        st.last_calc_ts = now_utc
                        st.last_sum_par_umol = par_sum

                current_dli = st.dli_capped_mol if cfg.use_capped_dli else st.dli_raw_mol
                target_reached = current_dli >= cfg.dli_target_mol

                # ------------------------------------------------
                # 2) hard off by off_window_end
                # ------------------------------------------------
                if _is_after_or_equal(now_t, cfg.off_window_end):
                    st.forced_off = True
                    if st.target_reached_at is None and target_reached:
                        st.target_reached_at = now_utc

                    sent += self._send_if_needed(
                        session=session,
                        svc=svc,
                        ui_id=ui_id,
                        enabled_topic=enabled_topic,
                        dim_topic=dim_topic,
                        decision=SendDecision(enabled=0, pwm_pct=0.0),
                        cur_enabled_num=cur_enabled_num,
                        cur_enabled_txt=cur_enabled_txt,
                        cur_dim_num=cur_dim_num,
                        cur_dim_txt=cur_dim_txt,
                    )
                    st.last_control_ts = now_utc
                    st.last_pwm_pct = 0.0
                    st.last_enabled = False
                    par_dli_crud.save_state(session, st)
                    continue

                # ------------------------------------------------
                # 3) DLI reached in off window
                # ------------------------------------------------
                if _time_in_window(now_t, cfg.off_window_start, cfg.off_window_end) and target_reached:
                    if st.target_reached_at is None:
                        st.target_reached_at = now_utc

                    sent += self._send_if_needed(
                        session=session,
                        svc=svc,
                        ui_id=ui_id,
                        enabled_topic=enabled_topic,
                        dim_topic=dim_topic,
                        decision=SendDecision(enabled=0, pwm_pct=0.0),
                        cur_enabled_num=cur_enabled_num,
                        cur_enabled_txt=cur_enabled_txt,
                        cur_dim_num=cur_dim_num,
                        cur_dim_txt=cur_dim_txt,
                    )
                    st.last_control_ts = now_utc
                    st.last_pwm_pct = 0.0
                    st.last_enabled = False
                    par_dli_crud.save_state(session, st)
                    continue

                # ------------------------------------------------
                # 4) before start_time => off
                # ------------------------------------------------
                if now_t < cfg.start_time:
                    sent += self._send_if_needed(
                        session=session,
                        svc=svc,
                        ui_id=ui_id,
                        enabled_topic=enabled_topic,
                        dim_topic=dim_topic,
                        decision=SendDecision(enabled=0, pwm_pct=0.0),
                        cur_enabled_num=cur_enabled_num,
                        cur_enabled_txt=cur_enabled_txt,
                        cur_dim_num=cur_dim_num,
                        cur_dim_txt=cur_dim_txt,
                    )
                    st.last_control_ts = now_utc
                    st.last_pwm_pct = 0.0
                    st.last_enabled = False
                    par_dli_crud.save_state(session, st)
                    continue

                # ------------------------------------------------
                # 5) correction interval gate
                # ------------------------------------------------
                if st.last_control_ts is not None:
                    elapsed = (now_utc - st.last_control_ts).total_seconds()
                    if elapsed < cfg.correction_interval_s:
                        skipped += 1
                        par_dli_crud.save_state(session, st)
                        continue

                new_pwm = _compute_pwm_pct(
                    par_top=par_top,
                    par_target=cfg.par_target_umol,
                    fixture_umol_100=cfg.fixture_umol_100,
                )

                deadband_pwm = (cfg.par_deadband_umol / cfg.fixture_umol_100) * 100.0
                prev_pwm = float(st.last_pwm_pct or 0.0)

                if abs(new_pwm - prev_pwm) < deadband_pwm:
                    skipped += 1
                    st.last_control_ts = now_utc
                    par_dli_crud.save_state(session, st)
                    continue

                enabled = 1 if new_pwm > 0.0 else 0

                sent += self._send_if_needed(
                    session=session,
                    svc=svc,
                    ui_id=ui_id,
                    enabled_topic=enabled_topic,
                    dim_topic=dim_topic,
                    decision=SendDecision(enabled=enabled, pwm_pct=new_pwm),
                    cur_enabled_num=cur_enabled_num,
                    cur_enabled_txt=cur_enabled_txt,
                    cur_dim_num=cur_dim_num,
                    cur_dim_txt=cur_dim_txt,
                )

                st.last_control_ts = now_utc
                st.last_pwm_pct = float(new_pwm)
                st.last_enabled = bool(enabled)

                if target_reached and st.target_reached_at is None:
                    st.target_reached_at = now_utc

                par_dli_crud.save_state(session, st)

            session.commit()

            par_dli_commands_sent_total.inc(sent)
            par_dli_commands_skipped_total.inc(skipped)

            if sent:
                logger.info("PAR_DLI tick: sent=%s skipped=%s elements=%s", sent, skipped, len(ui_ids))