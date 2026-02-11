# app/db/source_crud.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models_ui import UiHwSource, UiHwMember, UiElement, UiBinding
from app.db.models_sources import SourceBinding


def list_sources(session: Session) -> list[UiHwSource]:
    return session.execute(select(UiHwSource).order_by(UiHwSource.source_id.asc())).scalars().all()


def get_source(session: Session, source_id: str) -> UiHwSource | None:
    return session.execute(select(UiHwSource).where(UiHwSource.source_id == source_id)).scalar_one_or_none()


def list_source_members(session: Session, source_id: str) -> list[str]:
    rows = session.execute(
        select(UiHwMember.ui_id).where(UiHwMember.source_id == source_id)
    ).all()
    return [ui_id for (ui_id,) in rows]


def get_elements(session: Session, ui_ids: list[str]) -> list[UiElement]:
    if not ui_ids:
        return []
    return session.execute(
        select(UiElement).where(UiElement.ui_id.in_(ui_ids)).order_by(UiElement.ui_id.asc())
    ).scalars().all()


def list_source_bindings(session: Session, source_id: str) -> list[SourceBinding]:
    return session.execute(
        select(SourceBinding).where(SourceBinding.source_id == source_id).order_by(SourceBinding.bind_key.asc())
    ).scalars().all()


def upsert_source_binding(
    session: Session,
    source_id: str,
    bind_key: str,
    topic: str,
    value_type: str | None,
    required: bool,
    note: str | None,
):
    stmt = (
        pg_insert(SourceBinding)
        .values(
            source_id=source_id,
            bind_key=bind_key,
            topic=topic,
            value_type=value_type,
            required=required,
            note=note,
        )
        .on_conflict_do_update(
            index_elements=[SourceBinding.source_id, SourceBinding.bind_key],
            set_={
                "topic": pg_insert(SourceBinding).excluded.topic,
                "value_type": pg_insert(SourceBinding).excluded.value_type,
                "required": pg_insert(SourceBinding).excluded.required,
                "note": pg_insert(SourceBinding).excluded.note,
                "updated_at": "now()",
            },
        )
    )
    session.execute(stmt)


def get_line_bindings_for_ui_ids(session: Session, ui_ids: list[str]) -> list[tuple[str, str, str]]:
    """
    Возвращает (ui_id, bind_key, topic) для mqtt-bindings линий.
    """
    if not ui_ids:
        return []
    rows = session.execute(
        select(UiBinding.ui_id, UiBinding.bind_key, UiBinding.topic)
        .where(UiBinding.ui_id.in_(ui_ids))
        .where(UiBinding.source == "mqtt")
    ).all()
    return [(ui_id, bind_key, topic) for (ui_id, bind_key, topic) in rows]
