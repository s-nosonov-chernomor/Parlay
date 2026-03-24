# app/api/v1/schemas_query.py
from __future__ import annotations

from datetime import datetime
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
    par_sum_bind_key: str = Field(..., description="bind_key нижнего суммарного PAR датчика")
    enabled_bind_keys: list[str] = Field(..., description="bind_key включения света")
    start: datetime
    end: datetime
    dli_cap_umol: float | None = Field(default=None, description="Ограничение PAR для capped DLI")
    limit: int = Field(default=200000, description="Предохранитель")


class QueryDliRowOut(BaseModel):
    ui_id: str
    source_id: str | None = None
    zone_code: str | None = None

    par_sum_topic: str
    enabled_topics: list[str]

    dli_raw_mol: float
    dli_capped_mol: float


class QueryDliOut(BaseModel):
    rows: list[QueryDliRowOut]
    meta: dict