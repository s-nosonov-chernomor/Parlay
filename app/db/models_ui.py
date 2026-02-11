# app/db/models_ui.py
from __future__ import annotations

from datetime import datetime, time as dtime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Text, Time, Float, CheckConstraint, func
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UiElement(Base):
    __tablename__ = "ui_elements"

    ui_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ui_type: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[str] = mapped_column(Text, nullable=False)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    cz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col_n: Mapped[int | None] = mapped_column(Integer, nullable=True)

    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
class UiBinding(Base):
    __tablename__ = "ui_bindings"

    ui_id: Mapped[str] = mapped_column(ForeignKey("ui_elements.ui_id", ondelete="CASCADE"), primary_key=True)
    bind_key: Mapped[str] = mapped_column(Text, primary_key=True)

    # topic nullable для computed/virtual bind_key
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # mqtt|computed|constant|schedule|priva

    value_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
class UiElementState(Base):
    __tablename__ = "ui_element_state"

    ui_id: Mapped[str] = mapped_column(ForeignKey("ui_elements.ui_id", ondelete="CASCADE"), primary_key=True)
    mode_requested: Mapped[str] = mapped_column(Text, nullable=False)  # WEB|AUTO|PRIVA|MANUAL
    schedule_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
class UiHwSource(Base):
    __tablename__ = "ui_hw_sources"

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_topic: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
class UiHwMember(Base):
    __tablename__ = "ui_hw_members"

    source_id: Mapped[str] = mapped_column(ForeignKey("ui_hw_sources.source_id", ondelete="CASCADE"), primary_key=True)
    ui_id: Mapped[str] = mapped_column(ForeignKey("ui_elements.ui_id", ondelete="CASCADE"), primary_key=True)
class UiPrivaBinding(Base):
    __tablename__ = "ui_priva_bindings"

    ui_id: Mapped[str] = mapped_column(ForeignKey("ui_elements.ui_id", ondelete="CASCADE"), primary_key=True)
    bind_key: Mapped[str] = mapped_column(Text, primary_key=True)
    priva_topic: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
class Schedule(Base):
    __tablename__ = "schedules"

    schedule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    tz: Mapped[str] = mapped_column(Text, nullable=False, server_default="Europe/Riga")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
class ScheduleEvent(Base):
    __tablename__ = "schedule_events"

    schedule_id: Mapped[str] = mapped_column(ForeignKey("schedules.schedule_id", ondelete="CASCADE"), primary_key=True)
    bind_key: Mapped[str] = mapped_column(Text, primary_key=True)
    at_time: Mapped[dtime] = mapped_column(Time, primary_key=True)

    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(value_num IS NOT NULL AND value_text IS NULL) OR (value_num IS NULL AND value_text IS NOT NULL)",
            name="ck_schedule_events_value_oneof",
        ),
    )

