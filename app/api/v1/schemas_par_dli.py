# app/api/v1/schemas_par_dli.py

from __future__ import annotations

from datetime import date, datetime, time
from pydantic import BaseModel, Field, field_validator


class UiParDliConfigIn(BaseModel):
    start_time: time

    par_target_umol: float = Field(..., ge=0)
    par_deadband_umol: float = Field(..., ge=0)

    dli_target_mol: float = Field(..., ge=0)

    off_window_start: time
    off_window_end: time

    fixture_umol_100: float = Field(..., gt=0)
    correction_interval_s: int = Field(..., gt=0)

    par_top_bind_key: str
    par_sum_bind_key: str
    enabled_bind_key: str
    dim_bind_key: str

    use_capped_dli: bool = True
    tz: str = "Europe/Riga"

    @field_validator(
        "par_top_bind_key",
        "par_sum_bind_key",
        "enabled_bind_key",
        "dim_bind_key",
    )
    @classmethod
    def _non_empty(cls, v: str) -> str:
        s = str(v).strip()
        if not s:
            raise ValueError("bind_key must not be empty")
        return s


class UiParDliConfigOut(BaseModel):
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


class UiParDliStateOut(BaseModel):
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

    par_top_current: float | None = None
    par_sum_current: float | None = None
    progress_pct: float | None = None