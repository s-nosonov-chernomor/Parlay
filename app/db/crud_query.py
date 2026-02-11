from __future__ import annotations
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Parameter, Reading
from app.db.models_ui import UiBinding, UiHwMember
from app.db.models_sources import SourceBinding

def resolve_ui_sources(db: Session, ui_ids: list[str]) -> dict[str, str]:
    # ui_id -> source_id
    rows = db.execute(
        select(UiHwMember.ui_id, UiHwMember.source_id).where(UiHwMember.ui_id.in_(ui_ids))
    ).all()
    return {ui_id: source_id for ui_id, source_id in rows}

def resolve_line_topics(db: Session, ui_ids: list[str], bind_keys: list[str]):
    # returns list of dicts: {ui_id, bind_key, topic, note}
    rows = db.execute(
        select(UiBinding.ui_id, UiBinding.bind_key, UiBinding.topic, UiBinding.note)
        .where(UiBinding.ui_id.in_(ui_ids))
        .where(UiBinding.bind_key.in_(bind_keys))
        .where(UiBinding.topic.isnot(None))
    ).all()
    out = []
    for ui_id, bind_key, topic, note in rows:
        out.append({"ui_id": ui_id, "bind_key": bind_key, "topic": topic, "note": note})
    return out

def resolve_cabinet_topics(db: Session, source_ids: list[str], bind_keys: list[str]):
    # returns list of dicts: {source_id, bind_key, topic, note}
    rows = db.execute(
        select(SourceBinding.source_id, SourceBinding.bind_key, SourceBinding.topic, SourceBinding.note)
        .where(SourceBinding.source_id.in_(source_ids))
        .where(SourceBinding.bind_key.in_(bind_keys))
        .where(SourceBinding.topic.isnot(None))
    ).all()
    out = []
    for source_id, bind_key, topic, note in rows:
        out.append({"source_id": source_id, "bind_key": bind_key, "topic": topic, "note": note})
    return out

def fetch_reading_points(
    db: Session,
    topic: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
):
    pid = db.execute(select(Parameter.id).where(Parameter.topic == topic)).scalar_one_or_none()
    if pid is None:
        return []

    stmt = select(Reading).where(Reading.parameter_id == pid)
    if start:
        stmt = stmt.where(Reading.ts >= start)
    if end:
        stmt = stmt.where(Reading.ts <= end)

    stmt = stmt.order_by(Reading.ts.asc()).limit(limit)
    return db.execute(stmt).scalars().all()
