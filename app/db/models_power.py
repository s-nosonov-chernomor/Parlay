# app/db/models_power.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, Integer, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LinePowerConfig(Base):
    __tablename__ = "line_power_config"

    ui_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("ui_elements.ui_id", ondelete="CASCADE"),
        primary_key=True,
    )

    led_nominal_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    led_lamps_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    hps_nominal_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hps_lamps_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
