# app/api/v1/schemas.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class ParameterOut(BaseModel):
    id: int
    topic: str
    title: str | None = None
    kind: str | None = None
    unit: str | None = None
    is_control: bool


class LastValueOut(BaseModel):
    topic: str
    ts: datetime
    trigger: str | None = None
    status_code: int | None = None
    status_message: str | None = None
    silent_for_s: int | None = None
    value_num: float | None = None
    value_text: str | None = None


class ReadingOut(BaseModel):
    ts: datetime
    trigger: str | None = None
    status_source: str | None = None
    status_code: int | None = None
    status_message: str | None = None
    silent_for_s: int | None = None
    value_num: float | None = None
    value_text: str | None = None


class CommandIn(BaseModel):
    topic: str
    value: object | None = None
    as_json: bool = True
    requested_by: str | None = None
    correlation_id: str | None = None


class CommandOut(BaseModel):
    id: int
    topic: str
    topic_on: str
    payload: str
