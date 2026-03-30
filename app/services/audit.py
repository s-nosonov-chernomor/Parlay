from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app.db import auth_crud


def write_audit(
    db: Session,
    request: Request,
    *,
    current_user: dict | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    bind_key: str | None = None,
    value_json: dict | None = None,
) -> int:
    ip = request.client.host if request.client else None

    return auth_crud.write_audit(
        db,
        username=(current_user or {}).get("username"),
        role=(current_user or {}).get("role"),
        action=action,
        endpoint=request.url.path,
        method=request.method,
        entity_type=entity_type,
        entity_id=entity_id,
        bind_key=bind_key,
        value_json=value_json,
        ip=ip,
    )