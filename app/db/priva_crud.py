# app/db/priva_crud.py
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Parameter, ParameterLast
from app.db.models_ui import UiElementState, UiBinding, UiPrivaBinding, UiHwMember, UiHwSource


def list_priva_states(session: Session) -> list[str]:
    """
    ui_id в режиме PRIVA (requested).
    effective потом проверим через HW-block.
    """
    rows = session.execute(
        select(UiElementState.ui_id)
        .where(UiElementState.mode_requested == "PRIVA")
    ).all()
    return [str(ui_id) for (ui_id,) in rows]


def load_mqtt_bindings(session: Session, ui_ids: list[str]) -> dict[str, dict[str, UiBinding]]:
    """
    ui_id -> bind_key -> UiBinding (mqtt topic)
    """
    if not ui_ids:
        return {}
    rows = session.execute(
        select(UiBinding)
        .where(UiBinding.ui_id.in_(ui_ids))
        .where(UiBinding.source == "mqtt")
        .where(UiBinding.topic.isnot(None))
    ).scalars().all()

    out: dict[str, dict[str, UiBinding]] = defaultdict(dict)
    for b in rows:
        out[b.ui_id][b.bind_key] = b
    return out


def load_priva_bindings(session: Session, ui_ids: list[str]) -> dict[str, dict[str, UiPrivaBinding]]:
    """
    ui_id -> bind_key -> UiPrivaBinding (priva_topic)
    """
    if not ui_ids:
        return {}
    rows = session.execute(
        select(UiPrivaBinding)
        .where(UiPrivaBinding.ui_id.in_(ui_ids))
    ).scalars().all()

    out: dict[str, dict[str, UiPrivaBinding]] = defaultdict(dict)
    for p in rows:
        out[p.ui_id][p.bind_key] = p
    return out


def load_manual_topics(session: Session, ui_ids: list[str]) -> dict[str, str]:
    """
    ui_id -> manual_topic (топик "авто режим")
    """
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


def load_last_values(session: Session, topics: Iterable[str]) -> dict[str, tuple[float | None, str | None]]:
    tlist = list({t for t in topics if t})
    if not tlist:
        return {}
    rows = session.execute(
        select(Parameter.topic, ParameterLast.value_num, ParameterLast.value_text)
        .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
        .where(Parameter.topic.in_(tlist))
    ).all()

    out: dict[str, tuple[float | None, str | None]] = {}
    for topic, vnum, vtxt in rows:
        out[str(topic)] = (vnum, vtxt)
    return out
