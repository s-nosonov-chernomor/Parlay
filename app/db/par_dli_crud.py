# app/db/par_dli_crud.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import select, func, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Parameter, ParameterLast, Reading
from app.db.models_ui import (
    UiBinding,
    UiElement,
    UiElementState,
    UiHwMember,
    UiHwSource,
    UiParDliConfig,
    UiParDliState,
)


@dataclass(slots=True, frozen=True)
class BindingResolved:
    bind_key: str
    topic: str
    value_type: str | None


def ui_exists(session: Session, ui_id: str) -> bool:
    return session.execute(
        select(UiElement.ui_id).where(UiElement.ui_id == ui_id)
    ).scalar_one_or_none() is not None


def list_par_dli_states(session: Session) -> list[str]:
    rows = session.execute(
        select(UiElementState.ui_id)
        .where(UiElementState.mode_requested == "PAR_DLI")
        .order_by(UiElementState.ui_id.asc())
    ).all()
    return [str(ui_id) for (ui_id,) in rows]


def load_config(session: Session, ui_id: str) -> UiParDliConfig | None:
    return session.execute(
        select(UiParDliConfig).where(UiParDliConfig.ui_id == ui_id)
    ).scalar_one_or_none()


def upsert_config(session: Session, ui_id: str, payload) -> datetime:
    stmt = (
        pg_insert(UiParDliConfig)
        .values(
            ui_id=ui_id,
            start_time=payload.start_time,

            par_target_umol=payload.par_target_umol,
            par_deadband_umol=payload.par_deadband_umol,

            dli_target_mol=payload.dli_target_mol,

            off_window_start=payload.off_window_start,
            off_window_end=payload.off_window_end,

            fixture_umol_100=payload.fixture_umol_100,
            correction_interval_s=payload.correction_interval_s,

            par_top_bind_key=payload.par_top_bind_key,
            par_sum_bind_key=payload.par_sum_bind_key,
            enabled_bind_key=payload.enabled_bind_key,
            dim_bind_key=payload.dim_bind_key,

            use_capped_dli=payload.use_capped_dli,
            tz=payload.tz,
        )
        .on_conflict_do_update(
            index_elements=[UiParDliConfig.ui_id],
            set_={
                "start_time": payload.start_time,
                "par_target_umol": payload.par_target_umol,
                "par_deadband_umol": payload.par_deadband_umol,
                "dli_target_mol": payload.dli_target_mol,
                "off_window_start": payload.off_window_start,
                "off_window_end": payload.off_window_end,
                "fixture_umol_100": payload.fixture_umol_100,
                "correction_interval_s": payload.correction_interval_s,
                "par_top_bind_key": payload.par_top_bind_key,
                "par_sum_bind_key": payload.par_sum_bind_key,
                "enabled_bind_key": payload.enabled_bind_key,
                "dim_bind_key": payload.dim_bind_key,
                "use_capped_dli": payload.use_capped_dli,
                "tz": payload.tz,
                "updated_at": pg_insert(UiParDliConfig).excluded.updated_at,
            },
        )
        .returning(UiParDliConfig.updated_at)
    )
    return session.execute(stmt).scalar_one()


def load_state(session: Session, ui_id: str) -> UiParDliState | None:
    return session.execute(
        select(UiParDliState).where(UiParDliState.ui_id == ui_id)
    ).scalar_one_or_none()


def reset_state_for_day(session: Session, ui_id: str, local_date: date) -> UiParDliState:
    stmt = (
        pg_insert(UiParDliState)
        .values(
            ui_id=ui_id,
            local_date=local_date,
            dli_raw_mol=0.0,
            dli_capped_mol=0.0,
            last_calc_ts=None,
            last_sum_par_umol=None,
            last_control_ts=None,
            last_pwm_pct=None,
            last_enabled=None,
            target_reached_at=None,
            forced_off=False,
        )
        .on_conflict_do_update(
            index_elements=[UiParDliState.ui_id],
            set_={
                "local_date": local_date,
                "dli_raw_mol": 0.0,
                "dli_capped_mol": 0.0,
                "last_calc_ts": None,
                "last_sum_par_umol": None,
                "last_control_ts": None,
                "last_pwm_pct": None,
                "last_enabled": None,
                "target_reached_at": None,
                "forced_off": False,
                "updated_at": pg_insert(UiParDliState).excluded.updated_at,
            },
        )
    )
    session.execute(stmt)
    return load_state(session, ui_id)  # type: ignore[return-value]


def save_state(session: Session, st: UiParDliState) -> None:
    session.add(st)
    session.flush()


def load_mqtt_bindings(session: Session, ui_id: str, bind_keys: list[str]) -> dict[str, BindingResolved]:
    rows = session.execute(
        select(UiBinding.bind_key, UiBinding.topic, UiBinding.value_type)
        .where(
            UiBinding.ui_id == ui_id,
            UiBinding.bind_key.in_(bind_keys),
            UiBinding.source == "mqtt",
            UiBinding.topic.is_not(None),
        )
    ).all()

    out: dict[str, BindingResolved] = {}
    for bk, topic, vt in rows:
        if topic:
            out[str(bk)] = BindingResolved(bind_key=str(bk), topic=str(topic), value_type=vt)
    return out


def load_manual_topic(session: Session, ui_id: str) -> str | None:
    return session.execute(
        select(UiHwSource.manual_topic)
        .select_from(UiHwMember)
        .join(UiHwSource, UiHwSource.source_id == UiHwMember.source_id)
        .where(UiHwMember.ui_id == ui_id)
        .limit(1)
    ).scalar_one_or_none()


def load_last_values(session: Session, topics: Iterable[str]) -> dict[str, tuple[float | None, str | None, datetime | None]]:
    tlist = list({str(t) for t in topics if t})
    if not tlist:
        return {}

    rows = session.execute(
        select(Parameter.topic, ParameterLast.value_num, ParameterLast.value_text, ParameterLast.ts)
        .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
        .where(Parameter.topic.in_(tlist))
    ).all()

    out: dict[str, tuple[float | None, str | None, datetime | None]] = {}
    for topic, vnum, vtxt, ts in rows:
        out[str(topic)] = (vnum, vtxt, ts)
    return out

def calc_dli_from_history(
    session: Session,
    topic: str,
    start_ts: datetime,
    end_ts: datetime,
    cap_umol: float | None,
) -> tuple[float, float]:
    pid = session.execute(
        select(Parameter.id).where(Parameter.topic == topic)
    ).scalar_one_or_none()
    if pid is None:
        return 0.0, 0.0

    rows = session.execute(
        select(Reading.ts, Reading.value_num)
        .where(
            and_(
                Reading.parameter_id == pid,
                Reading.ts >= start_ts,
                Reading.ts <= end_ts,
                Reading.value_num.is_not(None),
            )
        )
        .order_by(Reading.ts.asc())
    ).all()

    if not rows:
        return 0.0, 0.0

    raw = 0.0
    capped = 0.0

    prev_ts, prev_val = rows[0]
    prev_val = float(prev_val or 0.0)

    for ts, val in rows[1:]:
        cur_val = float(val or 0.0)
        dt_s = max(0.0, (ts - prev_ts).total_seconds())
        raw += prev_val * dt_s / 1_000_000.0
        capped += min(prev_val, cap_umol if cap_umol is not None else prev_val) * dt_s / 1_000_000.0
        prev_ts = ts
        prev_val = cur_val

    # important: account the tail from the last sample up to end_ts
    tail_s = max(0.0, (end_ts - prev_ts).total_seconds())
    raw += prev_val * tail_s / 1_000_000.0
    capped += min(prev_val, cap_umol if cap_umol is not None else prev_val) * tail_s / 1_000_000.0

    return raw, capped