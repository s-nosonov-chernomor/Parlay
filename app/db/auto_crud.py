# app/db/auto_crud.py
from __future__ import annotations

from collections import defaultdict
from datetime import time as dtime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Parameter, ParameterLast
from app.db.models_ui import UiElementState, UiBinding, UiHwMember, UiHwSource, ScheduleEvent


def list_auto_states(session: Session) -> list[tuple[str, str]]:
    """
    Возвращает список (ui_id, schedule_id) для элементов в AUTO.
    schedule_id гарантированно не null (мы это валидируем в endpoint смены режима).
    """
    rows = session.execute(
        select(UiElementState.ui_id, UiElementState.schedule_id)
        .where(UiElementState.mode_requested == "AUTO")
    ).all()
    out: list[tuple[str, str]] = []
    for ui_id, schedule_id in rows:
        if schedule_id:
            out.append((str(ui_id), str(schedule_id)))
    return out


def load_mqtt_bindings(session: Session, ui_ids: list[str]) -> dict[str, list[UiBinding]]:
    """
    ui_id -> список mqtt bindings (topic not null).
    """
    if not ui_ids:
        return {}

    rows = session.execute(
        select(UiBinding)
        .where(UiBinding.ui_id.in_(ui_ids))
        .where(UiBinding.source == "mqtt")
        .where(UiBinding.topic.isnot(None))
    ).scalars().all()

    m: dict[str, list[UiBinding]] = defaultdict(list)
    for b in rows:
        m[b.ui_id].append(b)
    return m


def load_schedule_events(session: Session, schedule_ids: list[str]) -> dict[str, dict[str, list[ScheduleEvent]]]:
    """
    schedule_id -> bind_key -> list[ScheduleEvent] sorted by at_time asc
    """
    if not schedule_ids:
        return {}

    rows = session.execute(
        select(ScheduleEvent)
        .where(ScheduleEvent.schedule_id.in_(schedule_ids))
        .order_by(ScheduleEvent.schedule_id.asc(), ScheduleEvent.bind_key.asc(), ScheduleEvent.at_time.asc())
    ).scalars().all()

    out: dict[str, dict[str, list[ScheduleEvent]]] = defaultdict(lambda: defaultdict(list))
    for e in rows:
        out[e.schedule_id][e.bind_key].append(e)
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

    m: dict[str, str] = {}
    for ui_id, manual_topic in rows:
        if manual_topic:
            m[str(ui_id)] = str(manual_topic)
    return m


def load_last_values(session: Session, topics: Iterable[str]) -> dict[str, tuple[float | None, str | None]]:
    """
    topic -> (value_num, value_text) из parameter_last
    """
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
