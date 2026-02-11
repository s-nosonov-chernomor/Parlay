# app/api/v1/schemas_schedule.py
from __future__ import annotations

from datetime import time
from pydantic import BaseModel, Field


class ScheduleOut(BaseModel):
    schedule_id: str
    title: str
    tz: str


class ScheduleCreateIn(BaseModel):
    schedule_id: str = Field(..., description="Например schedule_1")
    title: str
    tz: str = "Europe/Riga"


class ScheduleUpdateIn(BaseModel):
    title: str | None = None
    tz: str | None = None


class ScheduleEventOut(BaseModel):
    bind_key: str
    at_time: time
    value_num: float | None = None
    value_text: str | None = None


class ScheduleDetailOut(BaseModel):
    schedule_id: str
    title: str
    tz: str
    events: list[ScheduleEventOut]


class ScheduleEventUpsertIn(BaseModel):
    bind_key: str
    at_time: time
    value_num: float | None = None
    value_text: str | None = None


class ScheduleEventDeleteIn(BaseModel):
    bind_key: str
    at_time: time
