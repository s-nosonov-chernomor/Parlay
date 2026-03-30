# app/api/v1/routes_ui_set.py
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.api.v1.schemas_ui_set import UiSetIn, UiSetOut

from app.db import ui_command_crud
from app.runtime_limiter import get_limiter
from app.main_runtime import get_command_service
from app.services.command_service import CommandRequest

from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.api.deps import get_db, require_admin
from app.services.audit import write_audit

router = APIRouter(prefix="/ui", tags=["ui"])


@router.post("/{ui_id}/set", response_model=UiSetOut)
def ui_set(
    ui_id: str,
    payload: UiSetIn,
    request: Request,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    # 1) HW block
    manual_hw, _manual_topic = ui_command_crud.compute_manual_hw(db, ui_id)
    if manual_hw:
        raise HTTPException(
            status_code=423,  # Locked
            detail="Hardware MANUAL switch is active (auto_mode=0). Control is locked.",
        )

    # 2) effective mode: если state нет — считаем WEB (для ПНР/отладки удобно)
    mode_req, _schedule_id = ui_command_crud.get_ui_mode_requested(db, ui_id)
    mode_effective = "WEB" if not mode_req else mode_req

    if mode_effective != "WEB":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Control is disabled in mode {mode_effective}. Switch to WEB mode to control.",
        )

    # 3) topic по bind_key
    topic = ui_command_crud.find_mqtt_topic(db, ui_id, payload.bind_key)
    if not topic:
        raise HTTPException(status_code=404, detail="Binding not found (ui_id+bind_key)")

    # 4) debounce per topic
    lim = get_limiter()
    if not lim.allow(topic):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too frequent command for this topic (debounce)",
        )

    # 5) send
    svc = get_command_service()
    cmd_id = svc.send(
        db,
        CommandRequest(
            topic=topic,
            value=payload.value,
            as_json=payload.as_json,
            requested_by=payload.requested_by,
            correlation_id=payload.correlation_id,

        ),
    )

    write_audit(
        db,
        request,
        current_user=current_user,
        action="ui_set",
        entity_type="ui",
        entity_id=ui_id,
        bind_key=payload.bind_key,
        value_json={"value": payload.value, "as_json": payload.as_json},
    )

    db.commit()

    topic_on = topic.rstrip("/") + "/on"
    if payload.as_json:
        out_payload = json.dumps({"value": payload.value}, ensure_ascii=False)
    else:
        out_payload = "" if payload.value is None else str(payload.value)

    return UiSetOut(
        id=cmd_id,
        ui_id=ui_id,
        bind_key=payload.bind_key,
        topic=topic,
        topic_on=topic_on,
        payload=out_payload,
        mode_effective=mode_effective,
    )
