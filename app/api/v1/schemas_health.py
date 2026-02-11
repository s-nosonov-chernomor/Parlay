# app/api/v1/schemas_health.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class CabinetHealthCell(BaseModel):
    source_id: str
    title: str | None = None

    # позиционирование для "шахматки" (берём из ui_hw_sources.meta, если есть)
    cz: int | None = None
    row_n: int | None = None
    col_n: int | None = None
    x: int | None = None
    y: int | None = None

    status: str  # "green" | "yellow" | "red" | "unknown"
    last_updated_at: datetime | None = None

    monitored_topics: int
    bad_status_count: int
    silent_warn_count: int
    silent_crit_count: int
    stale_count: int

    # полезно подсветить: какой bind_key/топик "хуже всех" (best-effort)
    worst_topic: str | None = None
    worst_reason: str | None = None
