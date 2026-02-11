# app/db/schedule_crud.py
from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models_ui import Schedule, ScheduleEvent


def list_schedules(session: Session) -> list[Schedule]:
    return session.execute(select(Schedule).order_by(Schedule.schedule_id.asc())).scalars().all()


def get_schedule(session: Session, schedule_id: str) -> Schedule | None:
    return session.execute(select(Schedule).where(Schedule.schedule_id == schedule_id)).scalar_one_or_none()


def get_schedule_events(session: Session, schedule_id: str) -> list[ScheduleEvent]:
    return (
        session.execute(
            select(ScheduleEvent)
            .where(ScheduleEvent.schedule_id == schedule_id)
            .order_by(ScheduleEvent.bind_key.asc(), ScheduleEvent.at_time.asc())
        )
        .scalars()
        .all()
    )


def create_schedule(session: Session, schedule_id: str, title: str, tz: str) -> None:
    session.add(Schedule(schedule_id=schedule_id, title=title, tz=tz))


def update_schedule(session: Session, schedule_id: str, title: str | None, tz: str | None) -> bool:
    s = get_schedule(session, schedule_id)
    if not s:
        return False
    if title is not None:
        s.title = title
    if tz is not None:
        s.tz = tz
    return True


def upsert_event(
    session: Session,
    schedule_id: str,
    bind_key: str,
    at_time,
    value_num: float | None,
    value_text: str | None,
) -> None:
    stmt = (
        pg_insert(ScheduleEvent)
        .values(
            schedule_id=schedule_id,
            bind_key=bind_key,
            at_time=at_time,
            value_num=value_num,
            value_text=value_text,
        )
        .on_conflict_do_update(
            index_elements=[ScheduleEvent.schedule_id, ScheduleEvent.bind_key, ScheduleEvent.at_time],
            set_={
                "value_num": pg_insert(ScheduleEvent).excluded.value_num,
                "value_text": pg_insert(ScheduleEvent).excluded.value_text,
            },
        )
    )
    session.execute(stmt)


def delete_event(session: Session, schedule_id: str, bind_key: str, at_time) -> int:
    stmt = (
        delete(ScheduleEvent)
        .where(ScheduleEvent.schedule_id == schedule_id)
        .where(ScheduleEvent.bind_key == bind_key)
        .where(ScheduleEvent.at_time == at_time)
    )
    res = session.execute(stmt)
    return int(res.rowcount or 0)
