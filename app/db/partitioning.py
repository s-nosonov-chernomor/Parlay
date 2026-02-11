# app/db/partitioning.py
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_next_month_partition(db: Session) -> None:
    """
    Создаёт партицию на следующий месяц (если нет).
    """
    db.execute(
        text(
            """
            SELECT create_reading_partition(
                (date_trunc('month', now()) + interval '1 month')::date,
                (date_trunc('month', now()) + interval '2 month')::date
            );
            """
        )
    )
    db.commit()
