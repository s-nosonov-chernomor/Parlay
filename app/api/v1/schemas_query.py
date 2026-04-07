from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from pydantic import BaseModel, Field


class QueryRunIn(BaseModel):
    ui_ids: list[str] = Field(..., description="Выбранные линии (ui_id карточек)")
    bind_keys: list[str] = Field(..., description="Выбранные параметры (bind_key)")
    start: datetime
    end: datetime
    bucket_s: int | None = Field(default=None, description="Если задано — агрегация по интервалу (сек)")
    limit: int = Field(default=200000, description="Предохранитель на кол-во строк")


class QueryRowOut(BaseModel):
    ts: datetime
    ui_id: str
    source_id: str | None = None
    zone_code: str | None = None

    bind_key: str
    note: str | None = None
    topic: str

    value_num: float | None = None
    value_text: str | None = None


class QueryRunOut(BaseModel):
    rows: list[QueryRowOut]
    columns: list[str]
    meta: dict


class QueryDliIn(BaseModel):
    ui_ids: list[str] = Field(..., description="Выбранные линии (ui_id карточек)")
    dli_bind_key: str = Field(..., description="bind_key датчика, по которому считаем DLI")
    start: datetime
    end: datetime
    mode: Literal["daily", "cumulative"] = Field(
        default="daily",
        description="daily — посуточно по агросуткам; cumulative — накопление за весь период",
    )
    agro_day_start_time: time | None = Field(
        default=None,
        description="Начало агросуток, например 06:00:00. Используется только для mode='daily'",
    )
    dli_cap_umol: float | None = Field(default=None, description="Ограничение PAR для capped DLI")
    limit: int = Field(default=200000, description="Предохранитель на кол-во строк")


class QueryDliRowOut(BaseModel):
    ts: datetime
    ui_id: str
    source_id: str | None = None
    zone_code: str | None = None

    bind_key: str
    topic: str

    raw_dli_mol: float
    capped_dli_mol: float


class QueryDliOut(BaseModel):
    rows: list[QueryDliRowOut]
    meta: dict