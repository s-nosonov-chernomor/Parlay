from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_authenticated, require_admin
from app.api.v1.schemas_schedule import (
    ScheduleOut,
    ScheduleCreateIn,
    ScheduleUpdateIn,
    ScheduleDetailOut,
    ScheduleEventOut,
    ScheduleEventUpsertIn,
    ScheduleEventDeleteIn,
)
from app.db import schedule_crud
from app.services.audit import write_audit

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleOut])
def list_schedules(
    current_user=Depends(require_authenticated),
    db: Session = Depends(get_db),
):
    rows = schedule_crud.list_schedules(db)
    return [ScheduleOut(schedule_id=s.schedule_id, title=s.title, tz=s.tz) for s in rows]


@router.post("", response_model=ScheduleOut)
def create_schedule(
    payload: ScheduleCreateIn,
    request: Request,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if schedule_crud.get_schedule(db, payload.schedule_id):
        raise HTTPException(status_code=409, detail="schedule_id already exists")

    schedule_crud.create_schedule(db, payload.schedule_id, payload.title, payload.tz)

    write_audit(
        db,
        request,
        current_user=current_user,
        action="schedule_create",
        entity_type="schedule",
        entity_id=payload.schedule_id,
        value_json={
            "title": payload.title,
            "tz": payload.tz,
        },
    )

    db.commit()

    return ScheduleOut(
        schedule_id=payload.schedule_id,
        title=payload.title,
        tz=payload.tz,
    )


@router.get("/{schedule_id}", response_model=ScheduleDetailOut)
def get_schedule(
    schedule_id: str,
    current_user=Depends(require_authenticated),
    db: Session = Depends(get_db),
):
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
def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdateIn,
    request: Request,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    ok = schedule_crud.update_schedule(db, schedule_id, payload.title, payload.tz)
    if not ok:
        raise HTTPException(status_code=404, detail="schedule not found")

    write_audit(
        db,
        request,
        current_user=current_user,
        action="schedule_update",
        entity_type="schedule",
        entity_id=schedule_id,
        value_json={
            "title": payload.title,
            "tz": payload.tz,
        },
    )

    db.commit()

    s = schedule_crud.get_schedule(db, schedule_id)
    assert s is not None

    return ScheduleOut(
        schedule_id=s.schedule_id,
        title=s.title,
        tz=s.tz,
    )


@router.post("/{schedule_id}/events")
def upsert_event(
    schedule_id: str,
    payload: ScheduleEventUpsertIn,
    request: Request,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    s = schedule_crud.get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="schedule not found")

    if (
        (payload.value_num is None and payload.value_text is None)
        or (payload.value_num is not None and payload.value_text is not None)
    ):
        raise HTTPException(status_code=400, detail="Provide exactly one of value_num or value_text")

    schedule_crud.upsert_event(
        db,
        schedule_id=schedule_id,
        bind_key=payload.bind_key,
        at_time=payload.at_time,
        value_num=payload.value_num,
        value_text=payload.value_text,
    )

    write_audit(
        db,
        request,
        current_user=current_user,
        action="schedule_event_upsert",
        entity_type="schedule",
        entity_id=schedule_id,
        bind_key=payload.bind_key,
        value_json={
            "at_time": payload.at_time.isoformat(),
            "value_num": payload.value_num,
            "value_text": payload.value_text,
        },
    )

    db.commit()
    return {"ok": True}


@router.delete("/{schedule_id}/events")
def delete_event(
    schedule_id: str,
    payload: ScheduleEventDeleteIn,
    request: Request,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    s = schedule_crud.get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="schedule not found")

    n = schedule_crud.delete_event(db, schedule_id, payload.bind_key, payload.at_time)

    write_audit(
        db,
        request,
        current_user=current_user,
        action="schedule_event_delete",
        entity_type="schedule",
        entity_id=schedule_id,
        bind_key=payload.bind_key,
        value_json={
            "at_time": payload.at_time.isoformat(),
        },
    )

    db.commit()
    return {"ok": True, "deleted": n}