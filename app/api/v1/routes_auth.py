from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.api.v1.schemas_auth import LoginIn, LoginOut, LogoutOut, MeOut
from app.db import auth_crud
from app.services.security import verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = auth_crud.get_user_by_username(db, payload.username)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    request.session.clear()
    request.session["user_id"] = int(user.id)
    request.session["username"] = user.username
    request.session["role"] = user.role

    return LoginOut(ok=True, username=user.username, role=user.role)


@router.post("/logout", response_model=LogoutOut)
def logout(request: Request):
    request.session.clear()
    return LogoutOut(ok=True)


@router.get("/me", response_model=MeOut)
def me(current_user=Depends(get_current_user)):
    return MeOut(username=current_user["username"], role=current_user["role"])