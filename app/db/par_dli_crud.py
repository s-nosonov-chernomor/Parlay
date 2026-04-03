# app/db/par_dli_crud.py
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update, delete, and_
from sqlalchemy.orm import Session

from app.db.models import Parameter, Reading
from app.db.models_ui import (
    UiParDliConfig,
    UiElementState,
    UiHwMember,
    UiHwSource,
)
from app.services.bind_resolver import resolve_binding_topic

def _cfg_to_dict(cfg: UiParDliConfig) -> dict:
    return {
        "par_id": cfg.par_id,
        "title": cfg.title,
        "start_time": cfg.start_time,
        "ppfd_setpoint_umol": cfg.ppfd_setpoint_umol,
        "par_deadband_umol": cfg.par_deadband_umol,
        "dli_target_mol": cfg.dli_target_mol,
        "dli_cap_umol": cfg.dli_cap_umol,
        "off_window_start": cfg.off_window_start,
        "off_window_end": cfg.off_window_end,
        "correction_interval_s": cfg.correction_interval_s,
        "par_top_bind_key": cfg.par_top_bind_key,
        "par_sum_bind_key": cfg.par_sum_bind_key,
        "enabled_bind_keys": cfg.enabled_bind_keys,
        "dim_bind_keys": cfg.dim_bind_keys,
        "use_dli_cap": cfg.use_dli_cap,
        "tz": cfg.tz,
        "updated_at": cfg.updated_at,
    }


def list_configs(session: Session) -> list[dict]:
    rows = session.execute(
        select(UiParDliConfig).order_by(UiParDliConfig.par_id.asc())
    ).scalars().all()
    return [_cfg_to_dict(r) for r in rows]


def get_config(session: Session, par_id: str) -> dict | None:
    row = session.execute(
        select(UiParDliConfig).where(UiParDliConfig.par_id == par_id)
    ).scalar_one_or_none()
    return _cfg_to_dict(row) if row else None


def create_config(session: Session, payload) -> dict:
    row = UiParDliConfig(
        par_id=payload.par_id,
        title=payload.title,
        start_time=payload.start_time,
        ppfd_setpoint_umol=payload.ppfd_setpoint_umol,
        par_deadband_umol=payload.par_deadband_umol,
        dli_target_mol=payload.dli_target_mol,
        dli_cap_umol=payload.dli_cap_umol,
        off_window_start=payload.off_window_start,
        off_window_end=payload.off_window_end,
        fixture_umol_100=1.0,  # legacy field, больше не используется
        correction_interval_s=payload.correction_interval_s,
        par_top_bind_key=payload.par_top_bind_key,
        par_sum_bind_key=payload.par_sum_bind_key,
        enabled_bind_keys=payload.enabled_bind_keys,
        dim_bind_keys=payload.dim_bind_keys,
        use_dli_cap=payload.use_dli_cap,
        tz=payload.tz,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return _cfg_to_dict(row)


def update_config(session: Session, par_id: str, payload) -> dict | None:
    row = session.execute(
        select(UiParDliConfig).where(UiParDliConfig.par_id == par_id)
    ).scalar_one_or_none()
    if not row:
        return None

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)

    session.add(row)
    session.flush()
    session.refresh(row)
    return _cfg_to_dict(row)


def delete_config(session: Session, par_id: str) -> int:
    # сначала отвяжем линии от сценария
    session.execute(
        update(UiElementState)
        .where(UiElementState.par_id == par_id)
        .values(par_id=None)
    )

    res = session.execute(
        delete(UiParDliConfig).where(UiParDliConfig.par_id == par_id)
    )
    return int(res.rowcount or 0)


def list_ui_for_par(session: Session, par_id: str) -> list[str]:
    rows = session.execute(
        select(UiElementState.ui_id)
        .where(UiElementState.mode_requested == "PAR_DLI")
        .where(UiElementState.par_id == par_id)
        .order_by(UiElementState.ui_id.asc())
    ).all()
    return [str(ui_id) for (ui_id,) in rows]

def local_day_start_utc(now_local: datetime) -> datetime:
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)

def load_series(
    session: Session,
    topic: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[tuple[datetime, float | None, str | None]]:
    pid = session.execute(
        select(Parameter.id).where(Parameter.topic == topic)
    ).scalar_one_or_none()
    if pid is None:
        return []

    rows = session.execute(
        select(Reading.ts, Reading.value_num, Reading.value_text)
        .where(
            and_(
                Reading.parameter_id == pid,
                Reading.ts >= start_ts,
                Reading.ts <= end_ts,
            )
        )
        .order_by(Reading.ts.asc())
    ).all()

    return [(ts, vnum, vtxt) for ts, vnum, vtxt in rows]

def load_last_before(
    session: Session,
    topic: str,
    before_ts: datetime,
) -> tuple[float | None, str | None] | None:
    pid = session.execute(
        select(Parameter.id).where(Parameter.topic == topic)
    ).scalar_one_or_none()
    if pid is None:
        return None

    row = session.execute(
        select(Reading.value_num, Reading.value_text)
        .where(
            and_(
                Reading.parameter_id == pid,
                Reading.ts < before_ts,
            )
        )
        .order_by(Reading.ts.desc())
        .limit(1)
    ).first()

    if not row:
        return None
    return row[0], row[1]

def _as_float(vnum: float | None, vtxt: str | None) -> float | None:
    if vnum is not None:
        return float(vnum)
    if vtxt is None:
        return None
    try:
        return float(str(vtxt).strip().replace(",", "."))
    except Exception:
        return None


def _daily_reset_boundaries(start_ts: datetime, end_ts: datetime, tz_name: str) -> list[datetime]:
    """
    Возвращает UTC timestamps локальных полуночей внутри интервала (start_ts, end_ts].
    """
    tz = ZoneInfo(tz_name)

    start_local = start_ts.astimezone(tz)
    end_local = end_ts.astimezone(tz)

    next_midnight_local = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if next_midnight_local <= start_local:
        next_midnight_local = next_midnight_local + timedelta(days=1)

    out: list[datetime] = []
    cur = next_midnight_local
    while cur <= end_local:
        out.append(cur.astimezone(timezone.utc))
        cur = cur + timedelta(days=1)
    return out


def calc_dli_series_for_topic(
    session: Session,
    topic: str,
    start_ts: datetime,
    end_ts: datetime,
    cap_umol: float | None,
    mode: str,
    tz_name: str = "Europe/Riga",
) -> list[tuple[datetime, float, float]]:
    """
    Считает ряд накопления DLI по одному topic датчика PAR.

    Возвращает список точек:
    (ts, raw_dli_mol, capped_dli_mol)

    mode:
      - 'daily'      -> сброс в локальную полночь Europe/Riga
      - 'cumulative' -> накопление за весь диапазон
    """
    if end_ts <= start_ts:
        return []

    initial = load_last_before(session, topic, start_ts)
    current_par = max(0.0, _as_float(initial[0], initial[1]) or 0.0) if initial else 0.0

    par_events = load_series(session, topic, start_ts, end_ts)

    events: list[tuple[datetime, str, float | None, str | None]] = []
    for ts, vnum, vtxt in par_events:
        events.append((ts, "__par__", vnum, vtxt))

    if mode == "daily":
        for boundary_ts in _daily_reset_boundaries(start_ts, end_ts, tz_name):
            events.append((boundary_ts, "__reset__", None, None))

    # гарантируем наличие конечной точки
    events.append((end_ts, "__end__", None, None))
    events.sort(key=lambda x: x[0])

    raw = 0.0
    capped = 0.0
    prev_ts = start_ts

    rows: list[tuple[datetime, float, float]] = []
    rows.append((start_ts, 0.0, 0.0))

    for ts, kind, vnum, vtxt in events:
        dt_s = max(0.0, (ts - prev_ts).total_seconds())

        if dt_s > 0:
            raw += current_par * dt_s / 1_000_000.0
            capped_par = min(current_par, cap_umol) if cap_umol is not None else current_par
            capped += capped_par * dt_s / 1_000_000.0

        if kind == "__reset__":
            raw = 0.0
            capped = 0.0
            rows.append((ts, 0.0, 0.0))
        else:
            if kind == "__par__":
                current_par = max(0.0, _as_float(vnum, vtxt) or 0.0)

            rows.append((ts, raw, capped))

        prev_ts = ts

    # уберем возможные подряд дубликаты по ts
    compact: list[tuple[datetime, float, float]] = []
    for item in rows:
        if compact and compact[-1][0] == item[0]:
            compact[-1] = item
        else:
            compact.append(item)

    return compact

def calc_dli_for_line(
    session: Session,
    par_sum_topic: str,
    enabled_topics: list[str],
    start_ts: datetime,
    end_ts: datetime,
    cap_umol: float | None,
) -> tuple[float, float]:
    """
    Считает DLI только на тех интервалах, где ХОТЯ БЫ ОДИН enabled-topic был == 1.
    """

    def as_int01(vnum: float | None, vtxt: str | None) -> int | None:
        if vnum is not None:
            return 0 if float(vnum) == 0.0 else 1
        if vtxt is None:
            return None
        s = str(vtxt).strip().lower()
        if s in {"0", "false", "off", "no"}:
            return 0
        if s in {"1", "true", "on", "yes"}:
            return 1
        try:
            f = float(s.replace(",", "."))
            return 0 if f == 0.0 else 1
        except Exception:
            return None

    def as_float(vnum: float | None, vtxt: str | None) -> float | None:
        if vnum is not None:
            return float(vnum)
        if vtxt is None:
            return None
        try:
            return float(str(vtxt).strip().replace(",", "."))
        except Exception:
            return None

    raw = 0.0
    capped = 0.0

    # initial values at interval start
    par_initial = load_last_before(session, par_sum_topic, start_ts)
    current_par = 0.0
    if par_initial:
        current_par = max(0.0, as_float(par_initial[0], par_initial[1]) or 0.0)

    enabled_state: dict[str, bool] = {}
    for topic in enabled_topics:
        val = load_last_before(session, topic, start_ts)
        bit = as_int01(val[0], val[1]) if val else None
        enabled_state[topic] = bool(bit == 1)

    # gather all events
    events: list[tuple[datetime, str, float | None, str | None]] = []

    for ts, vnum, vtxt in load_series(session, par_sum_topic, start_ts, end_ts):
        events.append((ts, "__par__", vnum, vtxt))

    for topic in enabled_topics:
        for ts, vnum, vtxt in load_series(session, topic, start_ts, end_ts):
            events.append((ts, topic, vnum, vtxt))

    events.sort(key=lambda x: x[0])

    prev_ts = start_ts

    def line_enabled_now() -> bool:
        return any(enabled_state.values())

    for ts, topic, vnum, vtxt in events:
        dt_s = max(0.0, (ts - prev_ts).total_seconds())

        if dt_s > 0 and line_enabled_now():
            raw += current_par * dt_s / 1_000_000.0
            capped += min(current_par, cap_umol if cap_umol is not None else current_par) * dt_s / 1_000_000.0

        # apply event
        if topic == "__par__":
            current_par = max(0.0, as_float(vnum, vtxt) or 0.0)
        else:
            bit = as_int01(vnum, vtxt)
            enabled_state[topic] = bool(bit == 1)

        prev_ts = ts

    # tail
    tail_s = max(0.0, (end_ts - prev_ts).total_seconds())
    if tail_s > 0 and line_enabled_now():
        raw += current_par * tail_s / 1_000_000.0
        capped += min(current_par, cap_umol if cap_umol is not None else current_par) * tail_s / 1_000_000.0

    return raw, capped

def load_manual_topic(session: Session, ui_id: str) -> str | None:
    return session.execute(
        select(UiHwSource.manual_topic)
        .select_from(UiHwMember)
        .join(UiHwSource, UiHwSource.source_id == UiHwMember.source_id)
        .where(UiHwMember.ui_id == ui_id)
        .limit(1)
    ).scalar_one_or_none()

def load_last_values(
    session: Session,
    topics: list[str],
) -> dict[str, tuple[float | None, str | None, datetime | None]]:
    out: dict[str, tuple[float | None, str | None, datetime | None]] = {}

    clean_topics = [t for t in topics if t]
    if not clean_topics:
        return out

    p_rows = session.execute(
        select(Parameter.id, Parameter.topic).where(Parameter.topic.in_(clean_topics))
    ).all()

    pid_to_topic = {pid: topic for pid, topic in p_rows}
    if not pid_to_topic:
        return out

    for topic in clean_topics:
        out[topic] = (None, None, None)

    for pid, topic in pid_to_topic.items():
        row = session.execute(
            select(Reading.value_num, Reading.value_text, Reading.ts)
            .where(Reading.parameter_id == pid)
            .order_by(Reading.ts.desc())
            .limit(1)
        ).first()

        if row:
            out[topic] = (row[0], row[1], row[2])

    return out