from __future__ import annotations

from datetime import datetime, time
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
    source: str
    value_type: str | None = None
    required: bool = False
    note: str | None = None


class UiStateOut(BaseModel):
    ui_id: str
    mode_requested: str | None = None
    mode_effective: str
    schedule_id: str | None = None
    par_id: str | None = None
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


class UiParDliConfigSnapOut(BaseModel):
    par_id: str
    title: str | None = None

    start_time: time

    ppfd_setpoint_umol: float
    par_deadband_umol: float

    dli_target_mol: float
    dli_cap_umol: float | None = None

    off_window_start: time
    off_window_end: time

    fixture_umol_100: float
    correction_interval_s: int

    par_top_bind_key: str
    par_sum_bind_key: str

    enabled_bind_keys: list[str]
    dim_bind_keys: list[str]

    use_dli_cap: bool
    tz: str
    updated_at: datetime


class UiSnapshotOut(BaseModel):
    page: str
    elements: list[UiElementOut]
    bindings: list[UiBindingOut]
    states: list[UiStateOut]
    last: list[TopicLastOut]
    par_dli_configs: list[UiParDliConfigSnapOut] = []