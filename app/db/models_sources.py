# app/db/models_sources.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceBinding(Base):
    __tablename__ = "source_bindings"

    source_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("ui_hw_sources.source_id", ondelete="CASCADE"),
        primary_key=True,
    )
    bind_key: Mapped[str] = mapped_column(Text, primary_key=True)

    topic: Mapped[str] = mapped_column(Text, nullable=False)

    value_type: Mapped[str | None] = mapped_column(Text, nullable=True)  # num/bool/text
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
