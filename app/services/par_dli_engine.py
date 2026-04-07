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
from app.services.bind_resolver import resolve_binding_topic

from app.metrics_par_dli import (
    par_dli_ticks_total,
    par_dli_elements_total,
    par_dli_commands_sent_total,
    par_dli_commands_skipped_total,
    par_dli_errors_total,
)

logger = logging.getLogger("par_dli")

PROBE_PWM_STEP = 10

def _compute_auto_carryover_dli(
    session,
    par_sum_topic: str,
    tz_name: str,
    agro_day_start_time: dtime,
    dli_target_mol: float,
    dli_cap_umol: float | None,
    use_dli_cap: bool,
    current_agro_day_start_local: datetime,
) -> tuple[float, float]:
    """
    Возвращает:
    - auto_carryover_mol
    - prev_day_actual_dli_mol

    Логика:
    carryover = target - fact за ПРЕДЫДУЩИЕ агросутки.
    Плюс = недобор.
    Минус = перебор.
    """
    prev_start_local = current_agro_day_start_local - timedelta(days=1)
    prev_end_local = current_agro_day_start_local

    prev_start_utc = prev_start_local.astimezone(timezone.utc)
    prev_end_utc = prev_end_local.astimezone(timezone.utc)

    prev_series = par_dli_crud.calc_dli_series_for_topic(
        session=session,
        topic=par_sum_topic,
        start_ts=prev_start_utc,
        end_ts=prev_end_utc,
        cap_umol=dli_cap_umol,
        mode="daily",
        tz_name=tz_name,
        agro_day_start_time=agro_day_start_time,
    )

    if prev_series:
        _ts, prev_raw, prev_capped = prev_series[-1]
    else:
        prev_raw, prev_capped = 0.0, 0.0

    prev_actual = prev_capped if use_dli_cap else prev_raw
    auto_carryover = float(dli_target_mol) - float(prev_actual)
    return float(auto_carryover), float(prev_actual)

def _fmt(v: object | None, digits: int = 2) -> str:
    if v is None:
        return "None"
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return str(v)


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


def _clamp_pwm_int(value: float | int | None) -> int:
    if value is None:
        return 0
    try:
        v = int(round(float(value)))
    except Exception:
        return 0
    return max(0, min(100, v))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _combine_on_agro_day(
    agro_day_start_local: datetime,
    value_t: dtime,
    agro_day_start_time: dtime,
) -> datetime:
    dt = agro_day_start_local.replace(
        hour=value_t.hour,
        minute=value_t.minute,
        second=value_t.second,
        microsecond=0,
    )
    if value_t < agro_day_start_time:
        dt += timedelta(days=1)
    return dt


def _normalize_interval(start_dt: datetime, end_dt: datetime) -> tuple[datetime, datetime]:
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _subtract_block(
    base_start: datetime,
    base_end: datetime,
    block_start: datetime,
    block_end: datetime,
) -> list[tuple[datetime, datetime]]:
    if block_end <= base_start or block_start >= base_end:
        return [(base_start, base_end)]

    out: list[tuple[datetime, datetime]] = []

    left_start = base_start
    left_end = min(base_end, block_start)
    if left_end > left_start:
        out.append((left_start, left_end))

    right_start = max(base_start, block_end)
    right_end = base_end
    if right_end > right_start:
        out.append((right_start, right_end))

    return out


def _build_allowed_segments(
    agro_day_start_local: datetime,
    agro_day_start_time: dtime,
    light_start_time: dtime,
    light_end_time: dtime,
    off_window_start: dtime,
    off_window_end: dtime,
) -> list[tuple[datetime, datetime]]:
    light_start = _combine_on_agro_day(agro_day_start_local, light_start_time, agro_day_start_time)
    light_end = _combine_on_agro_day(agro_day_start_local, light_end_time, agro_day_start_time)
    light_start, light_end = _normalize_interval(light_start, light_end)

    off_start = _combine_on_agro_day(agro_day_start_local, off_window_start, agro_day_start_time)
    off_end = _combine_on_agro_day(agro_day_start_local, off_window_end, agro_day_start_time)
    off_start, off_end = _normalize_interval(off_start, off_end)

    return _subtract_block(light_start, light_end, off_start, off_end)


def _is_in_any_segment(now_local: datetime, segments: list[tuple[datetime, datetime]]) -> tuple[bool, datetime | None]:
    for seg_start, seg_end in segments:
        if seg_start <= now_local < seg_end:
            return True, seg_start
    return False, None


def _remaining_active_seconds(now_local: datetime, segments: list[tuple[datetime, datetime]]) -> float:
    total = 0.0
    for seg_start, seg_end in segments:
        overlap_start = max(now_local, seg_start)
        overlap_end = seg_end
        if overlap_end > overlap_start:
            total += (overlap_end - overlap_start).total_seconds()
    return max(0.0, total)


def _compute_required_ppfd(
    current_dli_mol: float,
    effective_target_dli_mol: float,
    remaining_active_s: float,
    ppfd_min_umol: float,
    ppfd_max_umol: float,
) -> float:
    remaining_dli = max(0.0, effective_target_dli_mol - current_dli_mol)

    if remaining_dli <= 0:
        return 0.0

    if remaining_active_s <= 0:
        return ppfd_max_umol

    required_ppfd = remaining_dli * 1_000_000.0 / remaining_active_s
    return _clamp(required_ppfd, ppfd_min_umol, ppfd_max_umol)


def _compute_pwm_from_total_ppfd(
    current_sum: float,
    desired_sum: float,
    current_pwm: int,
) -> int:
    current_sum = max(0.0, float(current_sum))
    desired_sum = max(0.0, float(desired_sum))
    current_pwm = _clamp_pwm_int(current_pwm)

    if desired_sum <= 0:
        return 0

    if current_pwm <= 0:
        if current_sum < desired_sum:
            return PROBE_PWM_STEP
        return 0

    if current_sum <= 1e-6:
        return 100

    proposed = current_pwm * desired_sum / current_sum
    return _clamp_pwm_int(proposed)


def _limit_pwm_step(current_pwm: int, desired_pwm: int, max_step_pct: int) -> int:
    current_pwm = _clamp_pwm_int(current_pwm)
    desired_pwm = _clamp_pwm_int(desired_pwm)
    step = max(1, int(max_step_pct))

    if desired_pwm > current_pwm:
        return min(desired_pwm, current_pwm + step)
    if desired_pwm < current_pwm:
        return max(desired_pwm, current_pwm - step)
    return desired_pwm


def _limit_pwm_by_ramp(
    desired_pwm: int,
    now_local: datetime,
    current_segment_start_local: datetime | None,
    ramp_up_s: int,
) -> int:
    desired_pwm = _clamp_pwm_int(desired_pwm)

    if current_segment_start_local is None:
        return 0

    if ramp_up_s <= 0:
        return desired_pwm

    elapsed_s = max(0.0, (now_local - current_segment_start_local).total_seconds())
    ramp_cap = int(round(min(100.0, elapsed_s * 100.0 / float(ramp_up_s))))
    return min(desired_pwm, ramp_cap)


@dataclass(slots=True)
class RuntimeState:
    last_pwm: int | None = None
    last_par_sum: float | None = None
    last_ts: datetime | None = None


class ParDliEngine:
    """
    Новый PAR_DLI режим:
    - главная цель: DLI
    - текущий PPFD не фиксируется жёстко, а рассчитывается динамически
    - динамический PPFD ограничивается коридором min/max
    - учитывается перенос недобора/перебора прошлых суток
    - есть плавный розжиг и ограничение шага изменения ШИМ
    - par_top читается только для логов/диагностики
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

        self._last_run_by_par: dict[str, float] = {}
        self._runtime_by_ui: dict[str, RuntimeState] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="par-dli-engine", daemon=True)
        self._thread.start()
        logger.info("ParDliEngine запущен tick_s=%s tz=%s", self.tick_s, self.tz_default)

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

                agro_day_start_utc = par_dli_crud.local_day_start_utc(now_local, cfg["agro_day_start_time"])
                agro_day_start_local = agro_day_start_utc.astimezone(tz)

                allowed_segments = _build_allowed_segments(
                    agro_day_start_local=agro_day_start_local,
                    agro_day_start_time=cfg["agro_day_start_time"],
                    light_start_time=cfg["start_time"],
                    light_end_time=cfg["light_end_time"],
                    off_window_start=cfg["off_window_start"],
                    off_window_end=cfg["off_window_end"],
                )

                in_allowed_segment, current_segment_start_local = _is_in_any_segment(now_local, allowed_segments)
                remaining_active_s = _remaining_active_seconds(now_local, allowed_segments)

                for ui_id in ui_ids:
                    if sent >= self.max_commands_per_tick:
                        break

                    manual_topic = par_dli_crud.load_manual_topic(session, ui_id)
                    if manual_topic:
                        mvnum, mvtxt, _mts = par_dli_crud.load_last_values(session, [manual_topic]).get(
                            manual_topic, (None, None, None)
                        )
                        bit = _as_int01(mvnum, mvtxt)
                        if bit is not None and bit == 0:
                            skipped += 1
                            logger.info(
                                "PAR_DLI[%s][%s] skip: активирован ручной блок manual_topic=%s value=%s/%s",
                                par_id,
                                ui_id,
                                manual_topic,
                                _fmt(mvnum),
                                mvtxt,
                            )
                            continue

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

                    if not par_sum_topic or not enabled_topics or not dim_topics:
                        skipped += 1
                        logger.info(
                            "PAR_DLI[%s][%s] skip: unresolved bindings par_sum_topic=%s enabled_topics=%s dim_topics=%s",
                            par_id,
                            ui_id,
                            par_sum_topic,
                            enabled_topics,
                            dim_topics,
                        )
                        continue

                    topics_for_last = ([par_top_topic] if par_top_topic else []) + [par_sum_topic] + enabled_topics + dim_topics
                    last_map = par_dli_crud.load_last_values(session, topics_for_last)

                    par_top_num, par_top_txt, _ = last_map.get(par_top_topic, (None, None, None)) if par_top_topic else (None, None, None)
                    par_sum_num, par_sum_txt, _ = last_map.get(par_sum_topic, (None, None, None))

                    par_top = max(0.0, _coerce_float(par_top_num, par_top_txt) or 0.0)
                    par_sum = max(0.0, _coerce_float(par_sum_num, par_sum_txt) or 0.0)

                    current_enabled = False
                    for topic in enabled_topics:
                        vnum, vtxt, _ = last_map.get(topic, (None, None, None))
                        bit = _as_int01(vnum, vtxt)
                        if bit == 1:
                            current_enabled = True
                            break

                    dim_values: list[float] = []
                    for topic in dim_topics:
                        vnum, vtxt, _ = last_map.get(topic, (None, None, None))
                        val = _coerce_float(vnum, vtxt)
                        if val is not None:
                            dim_values.append(float(val))

                    current_pwm = _clamp_pwm_int(dim_values[0] if dim_values else 0)

                    dli_series = par_dli_crud.calc_dli_series_for_topic(
                        session=session,
                        topic=par_sum_topic,
                        start_ts=agro_day_start_utc,
                        end_ts=now_utc,
                        cap_umol=cfg["dli_cap_umol"],
                        mode="daily",
                        tz_name=tz_name,
                        agro_day_start_time=cfg["agro_day_start_time"],
                    )

                    if dli_series:
                        _ts, dli_raw, dli_capped = dli_series[-1]
                    else:
                        dli_raw, dli_capped = 0.0, 0.0

                    current_dli = dli_capped if cfg["use_dli_cap"] else dli_raw

                    auto_carryover_dli, prev_day_actual_dli = _compute_auto_carryover_dli(
                        session=session,
                        par_sum_topic=par_sum_topic,
                        tz_name=tz_name,
                        agro_day_start_time=cfg["agro_day_start_time"],
                        dli_target_mol=float(cfg["dli_target_mol"]),
                        dli_cap_umol=cfg["dli_cap_umol"],
                        use_dli_cap=bool(cfg["use_dli_cap"]),
                        current_agro_day_start_local=agro_day_start_local,
                    )

                    effective_target_dli = max(
                        0.0,
                        float(cfg["dli_target_mol"]) + float(auto_carryover_dli),
                    )

                    target_reached = current_dli >= effective_target_dli

                    desired_ppfd = _compute_required_ppfd(
                        current_dli_mol=current_dli,
                        effective_target_dli_mol=effective_target_dli,
                        remaining_active_s=remaining_active_s,
                        ppfd_min_umol=float(cfg["ppfd_min_umol"]),
                        ppfd_max_umol=float(cfg["ppfd_max_umol"]),
                    )

                    desired_enabled = 1
                    desired_pwm = current_pwm

                    if target_reached:
                        desired_enabled = 0
                        desired_pwm = 0
                    elif not in_allowed_segment:
                        desired_enabled = 0
                        desired_pwm = 0
                    else:
                        desired_enabled = 1

                        raw_pwm = _compute_pwm_from_total_ppfd(
                            current_sum=par_sum,
                            desired_sum=desired_ppfd,
                            current_pwm=current_pwm,
                        )

                        stepped_pwm = _limit_pwm_step(
                            current_pwm=current_pwm,
                            desired_pwm=raw_pwm,
                            max_step_pct=int(cfg["max_pwm_step_pct"]),
                        )

                        desired_pwm = _limit_pwm_by_ramp(
                            desired_pwm=stepped_pwm,
                            now_local=now_local,
                            current_segment_start_local=current_segment_start_local,
                            ramp_up_s=int(cfg["ramp_up_s"]),
                        )

                    runtime_dbg = self._runtime_by_ui.get(ui_id)
                    logger.info(
                        "PAR_DLI[%s][%s] state: "
                        "sum=%s top=%s current_dli=%s target_base=%s prev_day_actual=%s auto_carryover=%s target_eff=%s reached=%s "
                        "remaining_active_h=%s desired_ppfd=%s corridor=[%s..%s] "
                        "enabled_now=%s enabled_want=%s pwm_now=%s pwm_want=%s dim_all=%s "
                        "light_window=%s..%s off_window=%s..%s agro_start=%s ramp_up_s=%s max_pwm_step_pct=%s",
                        par_id,
                        ui_id,
                        _fmt(par_sum),
                        _fmt(par_top),
                        _fmt(current_dli, 3),
                        _fmt(cfg["dli_target_mol"], 3),
                        _fmt(prev_day_actual_dli, 3),
                        _fmt(auto_carryover_dli, 3),
                        _fmt(effective_target_dli, 3),
                        target_reached,
                        _fmt(remaining_active_s / 3600.0, 2),
                        _fmt(desired_ppfd),
                        _fmt(cfg["ppfd_min_umol"]),
                        _fmt(cfg["ppfd_max_umol"]),
                        int(bool(current_enabled)),
                        int(bool(desired_enabled)),
                        current_pwm,
                        int(desired_pwm),
                        [_clamp_pwm_int(v) for v in dim_values],
                        cfg["start_time"],
                        cfg["light_end_time"],
                        cfg["off_window_start"],
                        cfg["off_window_end"],
                        cfg["agro_day_start_time"],
                        cfg["ramp_up_s"],
                        cfg["max_pwm_step_pct"],
                    )

                    if bool(current_enabled) != bool(desired_enabled):
                        logger.info(
                            "PAR_DLI[%s][%s] enabled control: current=%s desired=%s topics=%s",
                            par_id,
                            ui_id,
                            int(bool(current_enabled)),
                            int(bool(desired_enabled)),
                            enabled_topics,
                        )
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

                    if not dim_values or any(_clamp_pwm_int(v) != int(desired_pwm) for v in dim_values):
                        logger.info(
                            "PAR_DLI[%s][%s] pwm control: current=%s desired=%s topics=%s",
                            par_id,
                            ui_id,
                            [_clamp_pwm_int(v) for v in dim_values],
                            int(desired_pwm),
                            dim_topics,
                        )
                        for topic in dim_topics:
                            svc.send(
                                session,
                                CommandRequest(
                                    topic=topic,
                                    value=int(desired_pwm),
                                    as_json=True,
                                    requested_by="par_dli",
                                    correlation_id=par_id,
                                ),
                            )
                            sent += 1
                    else:
                        skipped += 1

                    self._runtime_by_ui[ui_id] = RuntimeState(
                        last_pwm=int(desired_pwm),
                        last_par_sum=par_sum,
                        last_ts=now_utc,
                    )

                self._last_run_by_par[par_id] = now_mon

            session.commit()

            par_dli_elements_total.set(total_ui)
            par_dli_commands_sent_total.inc(sent)
            par_dli_commands_skipped_total.inc(skipped)

            if sent:
                logger.info("PAR_DLI tick: sent=%s skipped=%s elements=%s", sent, skipped, total_ui)