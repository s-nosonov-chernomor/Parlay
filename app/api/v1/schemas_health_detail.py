# app/api/v1/schemas_health_detail.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class HealthTopicIssue(BaseModel):
    topic: str
    bind_key: str | None = None
    severity: str  # ok|warn|crit|stale|missing|alarm
    reason: str | None = None
    ts: datetime | None = None
    status_code: int | None = None
    status_message: str | None = None
    silent_for_s: int | None = None
    value_num: float | None = None
    value_text: str | None = None


class LineHealth(BaseModel):
    ui_id: str
    title: str | None = None
    severity: str  # green|yellow|red|unknown
    bad_topics: int
    worst_topic: str | None = None
    worst_reason: str | None = None


class CabinetHealthDetail(BaseModel):
    source_id: str
    title: str | None = None
    status: str  # green|yellow|red|unknown

    last_updated_at: datetime | None = None

    manual_topic: str | None = None
    manual_switch_alarm: bool = False  # семантика: manual_topic.value == 0

    monitored_topics: int
    issues: list[HealthTopicIssue]

    members_count: int
    lines_red: int
    lines_yellow: int
    lines_green: int
    lines_unknown: int
    worst_lines: list[LineHealth]
