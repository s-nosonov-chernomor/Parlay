# app/api/v1/schemas_ui_mode.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class UiModeSetIn(BaseModel):
    mode_requested: str = Field(..., description="WEB|AUTO|PRIVA|PAR_DLI|MANUAL")
    schedule_id: str | None = Field(default=None, description="Обязателен только для AUTO")


class UiModeSetOut(BaseModel):
    ui_id: str
    mode_requested: str
    schedule_id: str | None
    updated_at: datetime

    manual_hw: bool
    alarm: bool
    mode_effective: str