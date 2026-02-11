# app/db/power_crud.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models_power import LinePowerConfig


def get_configs(session: Session, ui_ids: list[str]) -> dict[str, LinePowerConfig]:
    if not ui_ids:
        return {}
    rows = session.execute(
        select(LinePowerConfig).where(LinePowerConfig.ui_id.in_(ui_ids))
    ).scalars().all()
    return {r.ui_id: r for r in rows}


def upsert_config(
    session: Session,
    ui_id: str,
    led_nominal_w: int | None,
    led_lamps_count: int | None,
    hps_nominal_w: int | None,
    hps_lamps_count: int | None,
):
    stmt = (
        pg_insert(LinePowerConfig)
        .values(
            ui_id=ui_id,
            led_nominal_w=led_nominal_w,
            led_lamps_count=led_lamps_count,
            hps_nominal_w=hps_nominal_w,
            hps_lamps_count=hps_lamps_count,
        )
        .on_conflict_do_update(
            index_elements=[LinePowerConfig.ui_id],
            set_={
                "led_nominal_w": pg_insert(LinePowerConfig).excluded.led_nominal_w,
                "led_lamps_count": pg_insert(LinePowerConfig).excluded.led_lamps_count,
                "hps_nominal_w": pg_insert(LinePowerConfig).excluded.hps_nominal_w,
                "hps_lamps_count": pg_insert(LinePowerConfig).excluded.hps_lamps_count,
                "updated_at": "now()",
            },
        )
    )
    session.execute(stmt)
