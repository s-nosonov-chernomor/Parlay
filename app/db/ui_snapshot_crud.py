# app\db\ui_snapshot_crud.py
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models_ui import (
    UiElement,
    UiBinding,
    UiElementState,
    UiHwMember,
    UiHwSource,
    UiParDliConfig,
)
from app.db.models import Parameter, ParameterLast
from app.db import par_dli_crud
from app.services.bind_resolver import resolve_binding_topic


def load_elements(session: Session, page: str) -> list[UiElement]:
    return session.execute(
        select(UiElement).where(UiElement.page == page).order_by(UiElement.ui_id.asc())
    ).scalars().all()


def load_bindings(session: Session, ui_ids: list[str]) -> list[UiBinding]:
    if not ui_ids:
        return []
    return session.execute(
        select(UiBinding)
        .where(UiBinding.ui_id.in_(ui_ids))
        .order_by(UiBinding.ui_id.asc(), UiBinding.bind_key.asc())
    ).scalars().all()


def load_states(session: Session, ui_ids: list[str]) -> dict[str, UiElementState]:
    if not ui_ids:
        return {}
    rows = session.execute(
        select(UiElementState).where(UiElementState.ui_id.in_(ui_ids))
    ).scalars().all()
    return {s.ui_id: s for s in rows}


def load_manual_topics(session: Session, ui_ids: list[str]) -> dict[str, str]:
    if not ui_ids:
        return {}
    rows = session.execute(
        select(UiHwMember.ui_id, UiHwSource.manual_topic)
        .join(UiHwSource, UiHwSource.source_id == UiHwMember.source_id)
        .where(UiHwMember.ui_id.in_(ui_ids))
    ).all()

    out: dict[str, str] = {}
    for ui_id, manual_topic in rows:
        if manual_topic:
            out[str(ui_id)] = str(manual_topic)
    return out


def load_last_by_topics(session: Session, topics: list[str]) -> dict[str, tuple]:
    tlist = list({t for t in topics if t})
    if not tlist:
        return {}

    rows = session.execute(
        select(
            Parameter.topic,
            ParameterLast.ts,
            ParameterLast.status_code,
            ParameterLast.status_message,
            ParameterLast.silent_for_s,
            ParameterLast.value_num,
            ParameterLast.value_text,
        )
        .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
        .where(Parameter.topic.in_(tlist))
    ).all()

    out: dict[str, tuple] = {}
    for r in rows:
        out[str(r[0])] = r[1:]
    return out


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


def compute_state_effective(
    mode_requested: str | None,
    manual_hw: bool,
) -> str:
    if manual_hw:
        return "MANUAL_HW"
    if not mode_requested:
        return "WEB"
    return mode_requested


def load_par_dli_configs_by_ids(session: Session, par_ids: list[str]) -> dict[str, UiParDliConfig]:
    plist = list({p for p in par_ids if p})
    if not plist:
        return {}

    rows = session.execute(
        select(UiParDliConfig).where(UiParDliConfig.par_id.in_(plist))
    ).scalars().all()

    return {r.par_id: r for r in rows}

def load_par_dli_states_by_ui(
    session: Session,
    ui_to_cfg: dict[str, UiParDliConfig],
) -> dict[str, dict]:
    out: dict[str, dict] = {}

    for ui_id, cfg in ui_to_cfg.items():
        tz_name = (cfg.tz or "Europe/Riga").strip() or "Europe/Riga"
        tz = ZoneInfo(tz_name)

        par_sum_topic = resolve_binding_topic(session, ui_id, cfg.par_sum_bind_key)
        if not par_sum_topic:
            continue

        now_local = datetime.now(tz)
        now_utc = datetime.now(timezone.utc)
        agro_day_start_utc = par_dli_crud.local_day_start_utc(
            now_local,
            cfg.agro_day_start_time,
        )

        series = par_dli_crud.calc_dli_series_for_topic(
            session=session,
            topic=par_sum_topic,
            start_ts=agro_day_start_utc,
            end_ts=now_utc,
            cap_umol=cfg.dli_cap_umol,
            mode="daily",
            tz_name=tz_name,
            agro_day_start_time=cfg.agro_day_start_time,
        )

        if series:
            last_ts, dli_raw, dli_capped = series[-1]
        else:
            last_ts, dli_raw, dli_capped = now_utc, 0.0, 0.0

        current_dli = dli_capped if cfg.use_dli_cap else dli_raw
        progress_pct = 0.0
        if cfg.dli_target_mol and float(cfg.dli_target_mol) > 0:
            progress_pct = min(100.0, max(0.0, current_dli * 100.0 / float(cfg.dli_target_mol)))

        out[ui_id] = {
            "ui_id": ui_id,
            "local_date": agro_day_start_utc.astimezone(tz).date(),
            "dli_raw_mol": float(dli_raw),
            "dli_capped_mol": float(dli_capped),
            "last_calc_ts": last_ts,
            "last_sum_par_umol": None,
            "last_control_ts": None,
            "last_pwm_pct": None,
            "last_enabled": None,
            "target_reached_at": None,
            "forced_off": False,
            "updated_at": now_utc,
            "par_top_current": None,
            "par_sum_current": None,
            "progress_pct": float(progress_pct),
        }

    return out