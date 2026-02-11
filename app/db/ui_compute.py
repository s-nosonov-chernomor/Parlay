# app/db/ui_compute.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Parameter, ParameterLast
from app.db.models_ui import UiHwMember, UiHwSource


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


def compute_hw_flags(session: Session, ui_id: str) -> tuple[bool, bool, str | None]:
    """
    Возвращает: (manual_hw, alarm, manual_topic)
    manual_hw=True если manual_topic (авто режим) == 0.
    """
    manual_topic = session.execute(
        select(UiHwSource.manual_topic)
        .select_from(UiHwMember)
        .join(UiHwSource, UiHwSource.source_id == UiHwMember.source_id)
        .where(UiHwMember.ui_id == ui_id)
        .limit(1)
    ).scalar_one_or_none()

    if not manual_topic:
        return False, False, None

    row = session.execute(
        select(ParameterLast.value_num, ParameterLast.value_text)
        .select_from(Parameter)
        .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
        .where(Parameter.topic == manual_topic)
        .limit(1)
    ).first()

    if not row:
        return False, False, manual_topic

    vnum, vtxt = row
    bit = _as_int01(vnum, vtxt)
    manual_hw = (bit is not None and bit == 0)
    alarm = manual_hw
    return manual_hw, alarm, manual_topic
