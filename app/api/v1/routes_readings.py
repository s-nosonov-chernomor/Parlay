# app/api/v1/routes_readings.py
from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas import LastValueOut, ReadingOut
from app.db.models import Parameter, ParameterLast, Reading

router = APIRouter(prefix="/readings", tags=["readings"])


@router.get("/last", response_model=list[LastValueOut])
def last_values(
    prefix: str | None = Query(default=None, description="Например '/Черноморье/Дом/'"),
    topics: list[str] | None = Query(default=None, description="Конкретные topics (повторяющийся параметр)"),
    limit: int = 5000,
    db: Session = Depends(get_db),
):
    """
    Быстрый эндпоинт для экранов: читаем из parameter_last.
    Можно:
      - по prefix
      - по списку topics
    """
    stmt = (
        select(Parameter.topic, ParameterLast)
        .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
    )

    if topics:
        stmt = stmt.where(Parameter.topic.in_(topics))
    elif prefix:
        stmt = stmt.where(Parameter.topic.like(prefix + "%"))

    stmt = stmt.order_by(Parameter.topic.asc()).limit(limit)

    rows = db.execute(stmt).all()
    out: list[LastValueOut] = []
    for topic, last in rows:
        out.append(
            LastValueOut(
                topic=topic,
                ts=last.ts,
                trigger=last.trigger,
                status_code=last.status_code,
                status_message=last.status_message,
                silent_for_s=last.silent_for_s,
                value_num=last.value_num,
                value_text=last.value_text,
            )
        )
    return out


@router.get("/history", response_model=list[ReadingOut])
def history(
    topic: str = Query(..., description="Точный topic"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = 5000,
    db: Session = Depends(get_db),
):
    """
    История по конкретному topic за интервал.
    """
    pid = db.execute(select(Parameter.id).where(Parameter.topic == topic)).scalar_one_or_none()
    if pid is None:
        return []

    stmt = select(Reading).where(Reading.parameter_id == pid)
    if start:
        stmt = stmt.where(Reading.ts >= start)
    if end:
        stmt = stmt.where(Reading.ts <= end)

    stmt = stmt.order_by(Reading.ts.desc()).limit(limit)

    rows = db.execute(stmt).scalars().all()
    return [
        ReadingOut(
            ts=r.ts,
            trigger=r.trigger,
            status_source=r.status_source,
            status_code=r.status_code,
            status_message=r.status_message,
            silent_for_s=r.silent_for_s,
            value_num=r.value_num,
            value_text=r.value_text,
        )
        for r in rows
    ]
