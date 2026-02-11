# app/api/v1/schemas_ui.py
from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class UiBindingOut(BaseModel):
    bind_key: str
    source: str
    topic: str | None = None
    value_type: str | None = None
    required: bool = False
    note: str | None = None


class UiPrivaBindingOut(BaseModel):
    bind_key: str
    priva_topic: str
    note: str | None = None


class UiElementOut(BaseModel):
    ui_id: str
    ui_type: str
    page: str

    title: str | None = None
    cz: int | None = None
    row_n: int | None = None
    col_n: int | None = None
    meta: dict[str, Any]

    mode_requested: str
    schedule_id: str | None = None

    manual_hw: bool
    alarm: bool
    mode_effective: str

    # NEW: для отладки
    manual_topic: str | None = None

    bindings: list[UiBindingOut]
    priva: list[UiPrivaBindingOut] = []


class UiPageOut(BaseModel):
    page: str
    elements: list[UiElementOut]

    # NEW: темы для подписки (mqtt bindings)
    subscribe_topics: list[str]
