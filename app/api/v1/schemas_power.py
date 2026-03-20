# app/api/v1/schemas_power.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class LinePowerConfigIn(BaseModel):
    led_nominal_w: int | None = None
    led_lamps_count: int | None = None
    hps_nominal_w: int | None = None
    hps_lamps_count: int | None = None


class LinePowerOut(BaseModel):
    ui_id: str

    led_power_now: float | None = None
    led_power_ts: datetime | None = None   # ✅ добавили
    hps_power_now: float | None = None
    hps_power_ts: datetime | None = None   # ✅ добавили

    led_nominal_w: int | None = None
    led_lamps_count: int | None = None
    hps_nominal_w: int | None = None
    hps_lamps_count: int | None = None

    led_max_24h: float | None = None
    hps_max_24h: float | None = None

    led_burn_pct: float | None = None
    hps_burn_pct: float | None = None

    led_not_burning: int | None = None
    hps_not_burning: int | None = None
