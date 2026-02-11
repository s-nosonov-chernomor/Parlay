# app/api/v1/routes_commands.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.runtime_limiter import get_limiter

from app.api.auth import require_token
from app.api.deps import get_db
from app.api.v1.schemas import CommandIn, CommandOut
from app.services.command_service import CommandService, CommandRequest
from app.main_runtime import get_command_service

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post("", response_model=CommandOut, dependencies=[Depends(require_token)])
def send_command(payload: CommandIn, db: Session = Depends(get_db)):

    lim = get_limiter()
    if not lim.allow(payload.topic):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too frequent command for this topic (debounce)",
        )

    svc: CommandService = get_command_service()
    cmd_id = svc.send(
        db,
        CommandRequest(
            topic=payload.topic,
            value=payload.value,
            as_json=payload.as_json,
            requested_by=payload.requested_by,
            correlation_id=payload.correlation_id,
        ),
    )

    topic_on = payload.topic.rstrip("/") + "/on"
    out_payload = '{"value": null}'
    if payload.as_json:
        import json
        out_payload = json.dumps({"value": payload.value}, ensure_ascii=False)
    else:
        out_payload = "" if payload.value is None else str(payload.value)

    return CommandOut(id=cmd_id, topic=payload.topic, topic_on=topic_on, payload=out_payload)
