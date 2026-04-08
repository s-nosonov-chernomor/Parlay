# app\api\v1\schemas_par_dli.py
from __future__ import annotations

from datetime import datetime, time
from pydantic import BaseModel, Field, field_validator, model_validator


class UiParDliConfigIn(BaseModel):
    par_id: str = Field(..., description="Идентификатор сценария, например par_1")
    title: str | None = Field(default=None, description="Человекочитаемое имя сценария")

    start_time: time = Field(..., description="Начало разрешённого светового периода")
    light_end_time: time = Field(..., description="Конец разрешённого светового периода")
    agro_day_start_time: time = Field(..., description="Начало агрономических суток")

    ppfd_min_umol: float = Field(..., ge=0, description="Минимально допустимый PPFD в рабочем коридоре")
    ppfd_max_umol: float = Field(..., ge=0, description="Максимально допустимый PPFD в рабочем коридоре")

    dli_target_mol: float = Field(..., ge=0, description="Базовая целевая DLI за агросутки")
    dli_cap_umol: float | None = Field(default=None, ge=0, description="Ограничение PAR для полезного DLI")

    off_window_start: time
    off_window_end: time

    correction_interval_s: int = Field(..., gt=0, description="Период проверки и коррекции")
    ramp_up_s: int = Field(default=1800, ge=0, description="Время плавного розжига после начала свечения")
    max_pwm_step_pct: int = Field(default=10, ge=1, le=100, description="Максимальное изменение ШИМ за один цикл")

    par_top_bind_key: str
    par_sum_bind_key: str

    enabled_bind_keys: list[str] = Field(..., min_length=1)
    dim_bind_keys: list[str] = Field(..., min_length=1)

    use_dli_cap: bool = True
    tz: str = "Europe/Riga"

    @field_validator("par_id", "par_top_bind_key", "par_sum_bind_key")
    @classmethod
    def _non_empty_str(cls, v: str) -> str:
        s = str(v).strip()
        if not s:
            raise ValueError("value must not be empty")
        return s

    @field_validator("enabled_bind_keys", "dim_bind_keys")
    @classmethod
    def _non_empty_list(cls, values: list[str]) -> list[str]:
        out = []
        for v in values:
            s = str(v).strip()
            if not s:
                raise ValueError("bind_key must not be empty")
            out.append(s)
        return out

    @model_validator(mode="after")
    def _validate_ppfd_range(self):
        if self.ppfd_max_umol < self.ppfd_min_umol:
            raise ValueError("ppfd_max_umol must be >= ppfd_min_umol")
        return self


class UiParDliConfigUpdateIn(BaseModel):
    title: str | None = None

    start_time: time | None = None
    light_end_time: time | None = None
    agro_day_start_time: time | None = None

    ppfd_min_umol: float | None = Field(default=None, ge=0)
    ppfd_max_umol: float | None = Field(default=None, ge=0)

    dli_target_mol: float | None = Field(default=None, ge=0)
    dli_cap_umol: float | None = Field(default=None, ge=0)

    off_window_start: time | None = None
    off_window_end: time | None = None

    correction_interval_s: int | None = Field(default=None, gt=0)
    ramp_up_s: int | None = Field(default=None, ge=0)
    max_pwm_step_pct: int | None = Field(default=None, ge=1, le=100)

    par_top_bind_key: str | None = None
    par_sum_bind_key: str | None = None

    enabled_bind_keys: list[str] | None = None
    dim_bind_keys: list[str] | None = None

    use_dli_cap: bool | None = None
    tz: str | None = None


class UiParDliConfigOut(BaseModel):
    par_id: str
    title: str | None

    start_time: time
    light_end_time: time
    agro_day_start_time: time

    ppfd_min_umol: float
    ppfd_max_umol: float

    dli_target_mol: float
    dli_cap_umol: float | None

    off_window_start: time
    off_window_end: time

    correction_interval_s: int
    ramp_up_s: int
    max_pwm_step_pct: int

    par_top_bind_key: str
    par_sum_bind_key: str

    enabled_bind_keys: list[str]
    dim_bind_keys: list[str]

    use_dli_cap: bool
    tz: str

    updated_at: datetime