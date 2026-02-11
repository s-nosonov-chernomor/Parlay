# app/db/ui_command_crud.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models_ui import UiBinding, UiElementState, UiHwMember, UiHwSource
from app.db.models import Parameter, ParameterLast


def get_ui_mode_requested(session: Session, ui_id: str) -> tuple[str | None, str | None]:
    """
    Возвращает (mode_requested, schedule_id) из ui_element_state.
    Если нет строки — (None, None)
    """
    row = session.execute(
        select(UiElementState.mode_requested, UiElementState.schedule_id)
        .where(UiElementState.ui_id == ui_id)
        .limit(1)
    ).first()
    if not row:
        return None, None
    return row[0], row[1]


def get_manual_topic(session: Session, ui_id: str) -> str | None:
    return session.execute(
        select(UiHwSource.manual_topic)
        .select_from(UiHwMember)
        .join(UiHwSource, UiHwSource.source_id == UiHwMember.source_id)
        .where(UiHwMember.ui_id == ui_id)
        .limit(1)
    ).scalar_one_or_none()


def get_last_value_by_topic(session: Session, topic: str) -> tuple[float | None, str | None] | None:
    row = session.execute(
        select(ParameterLast.value_num, ParameterLast.value_text)
        .select_from(Parameter)
        .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
        .where(Parameter.topic == topic)
        .limit(1)
    ).first()
    if not row:
        return None
    return row[0], row[1]


def find_mqtt_topic(session: Session, ui_id: str, bind_key: str) -> str | None:
    return session.execute(
        select(UiBinding.topic)
        .where(UiBinding.ui_id == ui_id)
        .where(UiBinding.bind_key == bind_key)
        .where(UiBinding.source == "mqtt")
        .limit(1)
    ).scalar_one_or_none()


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


def compute_manual_hw(session: Session, ui_id: str) -> tuple[bool, str | None]:
    manual_topic = get_manual_topic(session, ui_id)
    if not manual_topic:
        return False, None
    lv = get_last_value_by_topic(session, manual_topic)
    if not lv:
        return False, manual_topic
    vnum, vtxt = lv
    bit = _as_int01(vnum, vtxt)
    manual_hw = (bit is not None and bit == 0)
    return manual_hw, manual_topic
