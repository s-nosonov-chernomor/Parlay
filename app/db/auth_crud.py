from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, AuditLog


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()


def create_user(
    session: Session,
    username: str,
    password_hash: str,
    role: str,
    is_active: bool = True,
) -> User:
    row = User(
        username=username,
        password_hash=password_hash,
        role=role,
        is_active=is_active,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def write_audit(
    session: Session,
    *,
    username: str | None,
    role: str | None,
    action: str,
    endpoint: str,
    method: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    bind_key: str | None = None,
    value_json: dict | None = None,
    ip: str | None = None,
) -> int:
    row = AuditLog(
        username=username,
        role=role,
        action=action,
        endpoint=endpoint,
        method=method,
        entity_type=entity_type,
        entity_id=entity_id,
        bind_key=bind_key,
        value_json=value_json,
        ip=ip,
    )
    session.add(row)
    session.flush()
    return int(row.id)