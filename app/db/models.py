# app/db/models.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text,
    func
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Parameter(Base):
    __tablename__ = "parameter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_control: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    readings: Mapped[list["Reading"]] = relationship(back_populates="parameter", lazy="noload")


class Reading(Base):
    __tablename__ = "reading"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("parameter.id", ondelete="CASCADE"), nullable=False)

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    silent_for_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    value_num: Mapped[float | None] = mapped_column(nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    parameter: Mapped["Parameter"] = relationship(back_populates="readings", lazy="joined")

    __table_args__ = (
        Index("ix_reading_param_ts_desc", "parameter_id", "ts"),
    )


class ParameterLast(Base):
    __tablename__ = "parameter_last"

    parameter_id: Mapped[int] = mapped_column(
        ForeignKey("parameter.id", ondelete="CASCADE"), primary_key=True
    )

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    silent_for_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    value_num: Mapped[float | None] = mapped_column(nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class CommandLog(Base):
    __tablename__ = "command_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    topic: Mapped[str] = mapped_column(Text, nullable=False)
    topic_on: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)

    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_command_created_at", "created_at"),
    )

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # admin | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_users_username", "username"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)

    action: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)

    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    bind_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_username", "username"),
    )