# app/api/v1/schemas_ui_snapshot.py
from __future__ import annotations

from datetime import date, datetime, time
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

    par_dli_configs: list[UiParDliConfigSnapOut] = []
    par_dli_states: list[UiParDliStateSnapOut] = []

class UiParDliConfigSnapOut(BaseModel):
    ui_id: str

    start_time: time

    par_target_umol: float
    par_deadband_umol: float
    dli_target_mol: float

    off_window_start: time
    off_window_end: time

    fixture_umol_100: float
    correction_interval_s: int

    par_top_bind_key: str
    par_sum_bind_key: str
    enabled_bind_key: str
    dim_bind_key: str

    use_capped_dli: bool
    tz: str
    updated_at: datetime


class UiParDliStateSnapOut(BaseModel):
    ui_id: str
    local_date: date

    dli_raw_mol: float
    dli_capped_mol: float

    last_calc_ts: datetime | None
    last_sum_par_umol: float | None

    last_control_ts: datetime | None
    last_pwm_pct: float | None
    last_enabled: bool | None

    target_reached_at: datetime | None
    forced_off: bool
    updated_at: datetime

    progress_pct: float | None = None