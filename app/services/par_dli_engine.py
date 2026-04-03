# app/services/par_dli_engine.py
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
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


# Коэффициент "не доходить до цели" на каждом цикле.
# 1.0 = идти ровно в расчётную точку
# 0.95 = подходить осторожнее
APPROACH_GAIN = 0.95

# Если ШИМ = 0 и не хватает света, а оценить мощность ещё не по чему,
# делаем маленький пробный шаг.
PROBE_PWM_STEP = 10

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

def _is_after_or_equal(now_t: dtime, border_t: dtime) -> bool:
    return now_t >= border_t

def _time_in_window(now_t: dtime, start_t: dtime, end_t: dtime) -> bool:
    if start_t <= end_t:
        return start_t <= now_t <= end_t
    return now_t >= start_t or now_t <= end_t

def _clamp_pwm_int(value: float | int | None) -> int:
    if value is None:
        return 0
    try:
        v = int(round(float(value)))
    except Exception:
        return 0
    return max(0, min(100, v))

def _lamp_delta(par_sum: float, par_top: float) -> float:
    return max(0.0, float(par_sum) - float(par_top))

@dataclass(slots=True)
class RuntimeState:
    last_pwm: int | None = None
    last_par_top: float | None = None
    last_par_sum: float | None = None
    last_light_delta: float | None = None
    last_estimated_full_scale: float | None = None
    last_ts: datetime | None = None


def _estimate_full_scale_from_history(
    prev_pwm: int | None,
    prev_light_delta: float | None,
    current_pwm: int | None,
    current_light_delta: float | None,
) -> float | None:
    """
    Оцениваем "полную управляемую мощность линии" в umol/m2/s
    по изменению ШИМ и изменению light_delta между двумя циклами.
    """
    if prev_pwm is None or current_pwm is None:
        return None
    if prev_light_delta is None or current_light_delta is None:
        return None

    dpwm = float(current_pwm) - float(prev_pwm)
    dlight = float(current_light_delta) - float(prev_light_delta)

    if abs(dpwm) < 1e-6:
        return None

    # Нужна согласованная реакция:
    # увеличили PWM -> вырос delta
    # уменьшили PWM -> упал delta
    if (dpwm > 0 and dlight <= 0) or (dpwm < 0 and dlight >= 0):
        return None

    full_scale = abs(dlight) * 100.0 / abs(dpwm)
    if full_scale <= 0:
        return None
    return float(full_scale)


def _choose_sync_pwm(
    dim_values: list[float],
    current_sum: float,
    target_sum: float,
    deadband_umol: float,
) -> int:
    """
    Если dim_bind_keys рассинхронизированы:
    - ниже цели -> синхронизируем вверх к максимуму
    - выше цели -> синхронизируем вниз к минимуму
    - внутри deadband -> к ближайшему среднему
    """
    if not dim_values:
        return 0

    if current_sum < (target_sum - deadband_umol):
        return _clamp_pwm_int(max(dim_values))

    if current_sum > (target_sum + deadband_umol):
        return _clamp_pwm_int(min(dim_values))

    avg = sum(dim_values) / len(dim_values)
    return _clamp_pwm_int(avg)


def _compute_next_pwm(
    target_sum: float,
    deadband_umol: float,
    current_sum: float,
    current_top: float,
    current_light_delta: float,
    current_pwm: int,
    runtime: RuntimeState | None,
) -> int:
    """
    Новая логика:
    1) регулируем по фактическому нижнему датчику (current_sum)
    2) используем light_delta = par_sum - par_top
    3) если есть история и шаг ШИМ между циклами — оцениваем управляемую мощность
    4) если истории нет — используем грубую оценку
    """
    if abs(current_sum - target_sum) <= deadband_umol:
        return _clamp_pwm_int(current_pwm)

    # если уже на потолке и всё равно не хватает — ничего не сделать
    if current_sum < target_sum and current_pwm >= 100:
        return 100

    # если уже на нуле и всё равно выше цели — тоже ничего не сделать
    if current_sum > target_sum and current_pwm <= 0:
        return 0

    estimated_full_scale: float | None = None
    if runtime is not None:
        estimated_full_scale = _estimate_full_scale_from_history(
            prev_pwm=runtime.last_pwm,
            prev_light_delta=runtime.last_light_delta,
            current_pwm=current_pwm,
            current_light_delta=current_light_delta,
        )
        if estimated_full_scale is None:
            estimated_full_scale = runtime.last_estimated_full_scale

    # Ниже цели → повышаем ШИМ
    if current_sum < target_sum:
        deficit = float(target_sum) - float(current_sum)

        if estimated_full_scale and estimated_full_scale > 0:
            add_pct = deficit / estimated_full_scale * 100.0 * APPROACH_GAIN
            return _clamp_pwm_int(current_pwm + add_pct)

        # грубый первый шаг:
        # если уже есть вклад света от ламп и есть ненулевой PWM,
        # считаем его целиком "нашим" и масштабируем
        if current_pwm > 0 and current_light_delta > 0:
            rough_target = float(current_pwm) * (float(target_sum) / float(current_light_delta)) * APPROACH_GAIN
            return _clamp_pwm_int(rough_target)

        # если ШИМ 0 и пока не по чему оценить — пробный шаг
        return _clamp_pwm_int(PROBE_PWM_STEP)

    # Выше цели → понижаем ШИМ
    excess = float(current_sum) - float(target_sum)

    if estimated_full_scale and estimated_full_scale > 0:
        dec_pct = excess / estimated_full_scale * 100.0 * APPROACH_GAIN
        return _clamp_pwm_int(current_pwm - dec_pct)

    if current_pwm > 0 and current_light_delta > 0:
        dec_pct = excess / current_light_delta * float(current_pwm) * APPROACH_GAIN
        return _clamp_pwm_int(float(current_pwm) - dec_pct)

    return _clamp_pwm_int(current_pwm)


class ParDliEngine:
    """
    PAR_DLI engine:
    - сценарии живут отдельно по par_id
    - линии ссылаются на сценарий через ui_element_state.par_id
    - DLI считаем по нижнему датчику (par_sum) за сутки
    - регулирование ШИМ делаем по:
        par_top / par_sum / разнице между ними
    - fixture_umol_100 больше не используется
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

        # runtime memory per ui_id
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
                    # logger.info(
                    #     "PAR_DLI[%s] cooldown skip: dt=%ss < correction_interval_s=%s",
                    #     par_id,
                    #     _fmt(now_mon - last_run, 1),
                    #     cfg["correction_interval_s"],
                    # )
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

                    # аппаратный блок
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
                        logger.info(
                            "PAR_DLI[%s][%s] skip: unresolved bindings par_top_topic=%s par_sum_topic=%s enabled_topics=%s dim_topics=%s",
                            par_id,
                            ui_id,
                            par_top_topic,
                            par_sum_topic,
                            enabled_topics,
                            dim_topics,
                        )
                        continue

                    topics_for_last = [par_top_topic, par_sum_topic] + enabled_topics + dim_topics
                    last_map = par_dli_crud.load_last_values(session, topics_for_last)

                    # текущие значения датчиков
                    par_top_num, par_top_txt, _ = last_map.get(par_top_topic, (None, None, None))
                    par_sum_num, par_sum_txt, _ = last_map.get(par_sum_topic, (None, None, None))

                    par_top = max(0.0, _coerce_float(par_top_num, par_top_txt) or 0.0)
                    par_sum = max(0.0, _coerce_float(par_sum_num, par_sum_txt) or 0.0)
                    light_delta = _lamp_delta(par_sum=par_sum, par_top=par_top)

                    # текущее состояние enabled
                    current_enabled = False
                    for topic in enabled_topics:
                        vnum, vtxt, _ = last_map.get(topic, (None, None, None))
                        bit = _as_int01(vnum, vtxt)
                        if bit == 1:
                            current_enabled = True
                            break

                    # все текущие ШИМ
                    dim_values: list[float] = []
                    dim_map: dict[str, float] = {}
                    for topic in dim_topics:
                        vnum, vtxt, _ = last_map.get(topic, (None, None, None))
                        val = _coerce_float(vnum, vtxt)
                        if val is not None:
                            dim_values.append(float(val))
                            dim_map[topic] = float(val)

                    current_pwm = _clamp_pwm_int(dim_values[0] if dim_values else 0)

                    # ------------------------------------------------
                    # 1) DLI за сутки по нижнему датчику, без enabled
                    # ------------------------------------------------
                    dli_series = par_dli_crud.calc_dli_series_for_topic(
                        session=session,
                        topic=par_sum_topic,
                        start_ts=day_start_utc,
                        end_ts=now_utc,
                        cap_umol=cfg["dli_cap_umol"],
                        mode="daily",
                        tz_name=tz_name,
                    )

                    if dli_series:
                        _ts, dli_raw, dli_capped = dli_series[-1]
                    else:
                        dli_raw, dli_capped = 0.0, 0.0

                    current_dli = dli_capped if cfg["use_dli_cap"] else dli_raw
                    target_reached = current_dli >= float(cfg["dli_target_mol"])

                    # ------------------------------------------------
                    # 2) решение по enabled
                    # ------------------------------------------------
                    desired_enabled = 1

                    if now_t < cfg["start_time"]:
                        desired_enabled = 0
                    elif _is_after_or_equal(now_t, cfg["off_window_end"]):
                        desired_enabled = 0
                    elif _time_in_window(now_t, cfg["off_window_start"], cfg["off_window_end"]) and target_reached:
                        desired_enabled = 0

                    runtime_dbg = self._runtime_by_ui.get(ui_id)
                    logger.info(
                        "PAR_DLI[%s][%s] состояние: top=%s sum=%s delta=%s target_ppfd=%s deadband=%s "
                        "dli_raw=%s dli_capped=%s current_dli=%s dli_target=%s target_reached=%s "
                        "enabled_now=%s enabled_want=%s dim_now=%s dim_all=%s "
                        "prev_pwm=%s prev_top=%s prev_sum=%s prev_delta=%s prev_fullscale=%s",
                        par_id,
                        ui_id,
                        _fmt(par_top),
                        _fmt(par_sum),
                        _fmt(light_delta),
                        _fmt(cfg["ppfd_setpoint_umol"]),
                        _fmt(cfg["par_deadband_umol"]),
                        _fmt(dli_raw, 3),
                        _fmt(dli_capped, 3),
                        _fmt(current_dli, 3),
                        _fmt(cfg["dli_target_mol"], 3),
                        target_reached,
                        int(bool(current_enabled)),
                        int(bool(desired_enabled)),
                        current_pwm,
                        [_clamp_pwm_int(v) for v in dim_values],
                        runtime_dbg.last_pwm if runtime_dbg else None,
                        _fmt(runtime_dbg.last_par_top) if runtime_dbg else None,
                        _fmt(runtime_dbg.last_par_sum) if runtime_dbg else None,
                        _fmt(runtime_dbg.last_light_delta) if runtime_dbg else None,
                        _fmt(runtime_dbg.last_estimated_full_scale) if runtime_dbg else None,
                    )

                    # ------------------------------------------------
                    # 3) если выключено по режиму — ШИМ в 0
                    # ------------------------------------------------
                    if desired_enabled == 0:
                        desired_pwm = 0
                    else:
                        # если ШИМы рассинхронизированы — сначала синхронизируем и выходим из круга
                        dim_ints = [_clamp_pwm_int(v) for v in dim_values]
                        if dim_ints and (max(dim_ints) - min(dim_ints) >= 1):
                            sync_pwm = _choose_sync_pwm(
                                dim_values=dim_values,
                                current_sum=par_sum,
                                target_sum=float(cfg["ppfd_setpoint_umol"]),
                                deadband_umol=float(cfg["par_deadband_umol"]),
                            )

                            logger.info(
                                "PAR_DLI[%s][%s] синхронизация: нижний_PAR=%s уставка=%s гистерезис=%s текущие_ШИМ=%s -> выравниваем=%s%%",
                                par_id,
                                ui_id,
                                _fmt(par_sum),
                                _fmt(cfg["ppfd_setpoint_umol"]),
                                _fmt(cfg["par_deadband_umol"]),
                                dim_ints,
                                sync_pwm,
                            )

                            for topic in dim_topics:
                                logger.info(
                                    "PAR_DLI[%s][%s] отправка_ШИМ: topic=%s value=%s%% reason=sync",
                                    par_id,
                                    ui_id,
                                    topic,
                                    sync_pwm,
                                )
                                svc.send(
                                    session,
                                    CommandRequest(
                                        topic=topic,
                                        value=int(sync_pwm),
                                        as_json=True,
                                        requested_by="par_dli",
                                        correlation_id=par_id,
                                    ),
                                )
                                sent += 1

                        runtime = self._runtime_by_ui.get(ui_id)

                        desired_pwm = _compute_next_pwm(
                            target_sum=float(cfg["ppfd_setpoint_umol"]),
                            deadband_umol=float(cfg["par_deadband_umol"]),
                            current_sum=par_sum,
                            current_top=par_top,
                            current_light_delta=light_delta,
                            current_pwm=current_pwm,
                            runtime=runtime,
                        )

                        logger.info(
                            "PAR_DLI[%s][%s] решение: current_pwm=%s -> desired_pwm=%s; "
                            "sum=%s target=%s top=%s delta=%s",
                            par_id,
                            ui_id,
                            current_pwm,
                            desired_pwm,
                            _fmt(par_sum),
                            _fmt(cfg["ppfd_setpoint_umol"]),
                            _fmt(par_top),
                            _fmt(light_delta),
                        )

                    # ------------------------------------------------
                    # 4) send enabled commands if needed
                    # ------------------------------------------------
                    if bool(current_enabled) != bool(desired_enabled):
                        logger.info(
                            "PAR_DLI[%s][%s] управление: current=%s desired=%s topics=%s",
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
                        logger.info(
                            "PAR_DLI[%s][%s] enabled-ok: current=%s desired=%s",
                            par_id,
                            ui_id,
                            int(bool(current_enabled)),
                            int(bool(desired_enabled)),
                        )

                    # ------------------------------------------------
                    # 5) send dim commands if needed
                    # только целые числа
                    # ------------------------------------------------
                    if not dim_values or any(_clamp_pwm_int(v) != int(desired_pwm) for v in dim_values):
                        logger.info(
                            "PAR_DLI[%s][%s] управление_ШИМ: текущие=%s -> устанавливаем=%s%% каналы=%s",
                            par_id,
                            ui_id,
                            [_clamp_pwm_int(v) for v in dim_values],
                            int(desired_pwm),
                            dim_topics,
                        )
                        for topic in dim_topics:
                            logger.info(
                                "PAR_DLI[%s][%s] отправка_ШИМ: topic=%s value=%s%% reason=control",
                                par_id,
                                ui_id,
                                topic,
                                int(desired_pwm),
                            )
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
                        logger.info(
                            "PAR_DLI[%s][%s] dim-ok: current_dim=%s desired_pwm=%s",
                            par_id,
                            ui_id,
                            [_clamp_pwm_int(v) for v in dim_values],
                            int(desired_pwm),
                        )

                    # ------------------------------------------------
                    # 6) update runtime memory
                    # ------------------------------------------------
                    runtime_prev = self._runtime_by_ui.get(ui_id)
                    estimated_full_scale = _estimate_full_scale_from_history(
                        prev_pwm=runtime_prev.last_pwm if runtime_prev else None,
                        prev_light_delta=runtime_prev.last_light_delta if runtime_prev else None,
                        current_pwm=current_pwm,
                        current_light_delta=light_delta,
                    )

                    self._runtime_by_ui[ui_id] = RuntimeState(
                        last_pwm=int(desired_pwm),
                        last_par_top=par_top,
                        last_par_sum=par_sum,
                        last_light_delta=light_delta,
                        last_estimated_full_scale=(
                            estimated_full_scale
                            if estimated_full_scale is not None
                            else (runtime_prev.last_estimated_full_scale if runtime_prev else None)
                        ),
                        last_ts=now_utc,
                    )
                    logger.info(
                        "PAR_DLI[%s][%s] сохранение: last_pwm=%s last_top=%s last_sum=%s last_delta=%s last_fullscale=%s",
                        par_id,
                        ui_id,
                        int(desired_pwm),
                        _fmt(par_top),
                        _fmt(par_sum),
                        _fmt(light_delta),
                        _fmt(
                            estimated_full_scale
                            if estimated_full_scale is not None
                            else (runtime_prev.last_estimated_full_scale if runtime_prev else None)
                        ),
                    )

                self._last_run_by_par[par_id] = now_mon

            session.commit()

            par_dli_elements_total.set(total_ui)
            par_dli_commands_sent_total.inc(sent)
            par_dli_commands_skipped_total.inc(skipped)

            if sent:
                logger.info("PAR_DLI tick: sent=%s skipped=%s elements=%s", sent, skipped, total_ui)