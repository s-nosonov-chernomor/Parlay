# app/db/crud.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Parameter, Reading, ParameterLast


@dataclass(slots=True)
class ReadingRow:
    topic: str
    parameter_id: int
    ts: object  # datetime
    trigger: str | None
    status_source: str | None
    status_code: int | None
    status_message: str | None
    silent_for_s: int | None
    value_num: float | None
    value_text: str | None
    raw: dict | None


def upsert_parameter(session: Session, topic: str) -> int:
    """
    Быстрый upsert через INSERT .. ON CONFLICT .. DO UPDATE RETURNING id.
    """
    stmt = (
        pg_insert(Parameter)
        .values(topic=topic)
        .on_conflict_do_update(
            index_elements=[Parameter.topic],
            set_={"topic": topic},
        )
        .returning(Parameter.id)
    )
    pid = session.execute(stmt).scalar_one()
    return int(pid)


def insert_readings(session: Session, rows: list[ReadingRow]):
    if not rows:
        return
    values = [
        dict(
            parameter_id=r.parameter_id,
            ts=r.ts,
            trigger=r.trigger,
            status_source=r.status_source,
            status_code=r.status_code,
            status_message=r.status_message,
            silent_for_s=r.silent_for_s,
            value_num=r.value_num,
            value_text=r.value_text,
            raw=r.raw,
        )
        for r in rows
    ]
    session.execute(pg_insert(Reading), values)


def upsert_last(session: Session, rows: list[ReadingRow]):
    """
    Обновляем last-значения по каждому parameter_id (последний по ts в батче).
    """
    if not rows:
        return

    # берём последний элемент для каждого parameter_id (по ts)
    latest: dict[int, ReadingRow] = {}
    for r in rows:
        prev = latest.get(r.parameter_id)
        if prev is None or r.ts >= prev.ts:
            latest[r.parameter_id] = r

    values = [
        dict(
            parameter_id=r.parameter_id,
            ts=r.ts,
            trigger=r.trigger,
            status_code=r.status_code,
            status_message=r.status_message,
            silent_for_s=r.silent_for_s,
            value_num=r.value_num,
            value_text=r.value_text,
        )
        for r in latest.values()
    ]

    stmt = (
        pg_insert(ParameterLast)
        .values(values)
        .on_conflict_do_update(
            index_elements=[ParameterLast.parameter_id],
            set_={
                "ts": pg_insert(ParameterLast).excluded.ts,
                "trigger": pg_insert(ParameterLast).excluded.trigger,
                "status_code": pg_insert(ParameterLast).excluded.status_code,
                "status_message": pg_insert(ParameterLast).excluded.status_message,
                "silent_for_s": pg_insert(ParameterLast).excluded.silent_for_s,
                "value_num": pg_insert(ParameterLast).excluded.value_num,
                "value_text": pg_insert(ParameterLast).excluded.value_text,
            },
        )
    )
    session.execute(stmt)

def latest_per_topic(rows: list[ReadingRow]) -> list[ReadingRow]:
    latest: dict[str, ReadingRow] = {}
    for r in rows:
        prev = latest.get(r.topic)
        if prev is None or r.ts >= prev.ts:
            latest[r.topic] = r
    return list(latest.values())
