# app/db/ui_snapshot_crud.py
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models_ui import UiElement, UiBinding, UiElementState, UiHwMember, UiHwSource
from app.db.models import Parameter, ParameterLast


def load_elements(session: Session, page: str) -> list[UiElement]:
    return session.execute(
        select(UiElement).where(UiElement.page == page).order_by(UiElement.ui_id.asc())
    ).scalars().all()


def load_bindings(session: Session, ui_ids: list[str]) -> list[UiBinding]:
    if not ui_ids:
        return []
    return session.execute(
        select(UiBinding).where(UiBinding.ui_id.in_(ui_ids)).order_by(UiBinding.ui_id.asc(), UiBinding.bind_key.asc())
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
