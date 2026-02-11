# app/api/v1/schemas_ui_set.py
from __future__ import annotations

from pydantic import BaseModel, Field


class UiSetIn(BaseModel):
    bind_key: str = Field(..., description="Например hps.dim / led.enabled")
    value: object | None = Field(default=None, description="int/float/str/bool/null")
    as_json: bool = True
    requested_by: str | None = None
    correlation_id: str | None = None


class UiSetOut(BaseModel):
    id: int
    ui_id: str
    bind_key: str
    topic: str
    topic_on: str
    payload: str
    mode_effective: str
