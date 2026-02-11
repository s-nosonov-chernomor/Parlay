# app/api/v1/schemas_cabinets.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class LastValue(BaseModel):
    topic: str
    ts: datetime | None = None
    status_code: int | None = None
    status_message: str | None = None
    silent_for_s: int | None = None
    value_num: float | None = None
    value_text: str | None = None


class CabinetOut(BaseModel):
    source_id: str
    title: str | None = None
    manual_topic: str | None = None
    meta: dict | None = None
    members_count: int


class CabinetBindingOut(BaseModel):
    bind_key: str
    topic: str
    value_type: str | None = None
    required: bool = False
    note: str | None = None
    last: LastValue | None = None


class CabinetLineOut(BaseModel):
    ui_id: str
    title: str | None = None
    cz: int | None = None
    row_n: int | None = None
    col_n: int | None = None
    meta: dict | None = None
    # значения линии: bind_key -> last
    values: dict[str, LastValue] = {}


class CabinetSnapshotOut(BaseModel):
    cabinet: CabinetOut
    cabinet_values: list[CabinetBindingOut]
    lines: list[CabinetLineOut]
