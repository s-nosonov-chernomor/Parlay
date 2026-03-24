# app/services/bind_resolver.py
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models_ui import UiBinding, UiHwMember
from app.db.models_sources import SourceBinding


def resolve_binding_topic(session: Session, ui_id: str, bind_key: str) -> str | None:
    # 1. ищем в ui_bindings
    row = session.execute(
        select(UiBinding.topic)
        .where(UiBinding.ui_id == ui_id)
        .where(UiBinding.bind_key == bind_key)
        .where(UiBinding.topic.is_not(None))
    ).scalar_one_or_none()

    if row:
        return row

    # 2. ищем через source
    row = session.execute(
        select(SourceBinding.topic)
        .join(UiHwMember, UiHwMember.source_id == SourceBinding.source_id)
        .where(UiHwMember.ui_id == ui_id)
        .where(SourceBinding.bind_key == bind_key)
    ).scalar_one_or_none()

    return row