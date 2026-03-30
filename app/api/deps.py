from __future__ import annotations

from typing import Generator, Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request) -> dict[str, Any]:
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    role = request.session.get("role")

    if not user_id or not username or role not in {"admin", "viewer"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return {
        "user_id": user_id,
        "username": username,
        "role": role,
    }


def require_admin(current_user=...):
    # placeholder for typing editor friendliness
    return current_user

from fastapi import Depends


def require_authenticated(current_user=Depends(get_current_user)):
    return current_user


def require_admin(current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user