# app/api/v1/schemas_ui_snapshot.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class UiElementOut(BaseModel):
    ui_id: str
    ui_type: str
    page: str
    title: str | None = None
    cz: int | None = None
    row_n: int | None = None
    col_n: int | None = None
    meta: dict


class UiBindingOut(BaseModel):
    ui_id: str
    bind_key: str
    topic: str | None = None
    source: str  # mqtt|derived|priva
    value_type: str | None = None
    required: bool = False
    note: str | None = None


class UiStateOut(BaseModel):
    ui_id: str
    mode_requested: str | None = None
    mode_effective: str
    schedule_id: str | None = None
    manual_hw: bool
    manual_topic: str | None = None


class TopicLastOut(BaseModel):
    topic: str
    ts: datetime | None = None
    status_code: int | None = None
    status_message: str | None = None
    silent_for_s: int | None = None
    value_num: float | None = None
    value_text: str | None = None


class UiSnapshotOut(BaseModel):
    page: str
    elements: list[UiElementOut]
    bindings: list[UiBindingOut]
    states: list[UiStateOut]
    last: list[TopicLastOut]
