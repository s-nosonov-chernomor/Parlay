# app/db/ui_state_crud.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models_ui import UiElement, UiElementState


def ensure_ui_exists(session: Session, ui_id: str) -> bool:
    return session.execute(select(UiElement.ui_id).where(UiElement.ui_id == ui_id)).scalar_one_or_none() is not None


def upsert_ui_state(session: Session, ui_id: str, mode_requested: str, schedule_id: str | None) -> datetime:
    """
    Upsert ui_element_state(ui_id) -> (mode_requested, schedule_id, updated_at=now()).
    Возвращает updated_at.
    """
    stmt = (
        pg_insert(UiElementState)
        .values(ui_id=ui_id, mode_requested=mode_requested, schedule_id=schedule_id)
        .on_conflict_do_update(
            index_elements=[UiElementState.ui_id],
            set_={
                "mode_requested": mode_requested,
                "schedule_id": schedule_id,
                "updated_at": pg_insert(UiElementState).excluded.updated_at,
            },
        )
        .returning(UiElementState.updated_at)
    )
    ts = session.execute(stmt).scalar_one()
    return ts
