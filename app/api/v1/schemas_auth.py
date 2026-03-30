from __future__ import annotations

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(...)
    password: str = Field(...)


class MeOut(BaseModel):
    username: str
    role: str


class LoginOut(BaseModel):
    ok: bool
    username: str
    role: str


class LogoutOut(BaseModel):
    ok: bool