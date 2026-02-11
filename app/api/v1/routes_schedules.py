# app/api/v1/routes_schedules.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas_schedule import (
    ScheduleOut, ScheduleCreateIn, ScheduleUpdateIn,
    ScheduleDetailOut, ScheduleEventOut,
    ScheduleEventUpsertIn, ScheduleEventDeleteIn,
)
from app.db import schedule_crud


router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleOut])
def list_schedules(db: Session = Depends(get_db)):
    rows = schedule_crud.list_schedules(db)
    return [ScheduleOut(schedule_id=s.schedule_id, title=s.title, tz=s.tz) for s in rows]


@router.post("", response_model=ScheduleOut)
def create_schedule(payload: ScheduleCreateIn, db: Session = Depends(get_db)):
    if schedule_crud.get_schedule(db, payload.schedule_id):
        raise HTTPException(status_code=409, detail="schedule_id already exists")
    schedule_crud.create_schedule(db, payload.schedule_id, payload.title, payload.tz)
    db.commit()
    return ScheduleOut(schedule_id=payload.schedule_id, title=payload.title, tz=payload.tz)


@router.get("/{schedule_id}", response_model=ScheduleDetailOut)
def get_schedule(schedule_id: str, db: Session = Depends(get_db)):
    s = schedule_crud.get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="schedule not found")
    ev = schedule_crud.get_schedule_events(db, schedule_id)
    return ScheduleDetailOut(
        schedule_id=s.schedule_id,
        title=s.title,
        tz=s.tz,
        events=[
            ScheduleEventOut(
                bind_key=e.bind_key,
                at_time=e.at_time,
                value_num=e.value_num,
                value_text=e.value_text,
            )
            for e in ev
        ],
    )


@router.put("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: str, payload: ScheduleUpdateIn, db: Session = Depends(get_db)):
    ok = schedule_crud.update_schedule(db, schedule_id, payload.title, payload.tz)
    if not ok:
        raise HTTPException(status_code=404, detail="schedule not found")
    db.commit()
    s = schedule_crud.get_schedule(db, schedule_id)
    assert s is not None
    return ScheduleOut(schedule_id=s.schedule_id, title=s.title, tz=s.tz)


@router.post("/{schedule_id}/events")
def upsert_event(schedule_id: str, payload: ScheduleEventUpsertIn, db: Session = Depends(get_db)):
    s = schedule_crud.get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="schedule not found")

    # валидация: ровно одно значение
    if (payload.value_num is None and payload.value_text is None) or (payload.value_num is not None and payload.value_text is not None):
        raise HTTPException(status_code=400, detail="Provide exactly one of value_num or value_text")

    schedule_crud.upsert_event(
        db,
        schedule_id=schedule_id,
        bind_key=payload.bind_key,
        at_time=payload.at_time,
        value_num=payload.value_num,
        value_text=payload.value_text,
    )
    db.commit()
    return {"ok": True}


@router.delete("/{schedule_id}/events")
def delete_event(schedule_id: str, payload: ScheduleEventDeleteIn, db: Session = Depends(get_db)):
    s = schedule_crud.get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="schedule not found")

    n = schedule_crud.delete_event(db, schedule_id, payload.bind_key, payload.at_time)
    db.commit()
    return {"ok": True, "deleted": n}
