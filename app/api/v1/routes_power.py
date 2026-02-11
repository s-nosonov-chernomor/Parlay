# app/api/v1/routes_power.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models_ui import UiElement, UiBinding
from app.db.models import Parameter, ParameterLast, Reading
from app.db import power_crud
from app.api.v1.schemas_power import LinePowerOut, LinePowerConfigIn
from app.api.auth import require_token  # если хочешь защитить запись токеном

router = APIRouter(prefix="/power", tags=["power"])


@router.get("/page/{page}/snapshot", response_model=list[LinePowerOut])
def power_page_snapshot(page: str, db: Session = Depends(get_db)):
    # 1) линии на странице
    elements = db.execute(
        select(UiElement).where(UiElement.page == page).order_by(UiElement.ui_id.asc())
    ).scalars().all()
    ui_ids = [e.ui_id for e in elements if e.ui_type in ("zone_card", "line", "line_card")]

    if not ui_ids:
        return []

    # 2) bindings led.power/hps.power
    bindings = db.execute(
        select(UiBinding.ui_id, UiBinding.bind_key, UiBinding.topic)
        .where(UiBinding.ui_id.in_(ui_ids))
        .where(UiBinding.bind_key.in_(["led.power", "hps.power"]))
        .where(UiBinding.source == "mqtt")
    ).all()

    topic_by = {(ui_id, bind_key): topic for (ui_id, bind_key, topic) in bindings if topic}

    # topics для last
    topics = list({t for t in topic_by.values() if t})

    # 3) last (текущие мощности)
    last_rows = db.execute(
        select(
            Parameter.topic,
            ParameterLast.value_num,
            ParameterLast.value_text,
        )
        .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
        .where(Parameter.topic.in_(topics))
    ).all()
    last_map = {t: (vn, vt) for (t, vn, vt) in last_rows}

    def last_num(topic: str | None) -> float | None:
        if not topic:
            return None
        vn, vt = last_map.get(topic, (None, None))
        if vn is not None:
            return float(vn)
        # иногда мощность может прийти текстом — пробуем распарсить
        if vt is None:
            return None
        try:
            return float(str(vt).replace(",", "."))
        except Exception:
            return None

    # 4) configs
    cfg_map = power_crud.get_configs(db, ui_ids)

    # 5) max за 24 часа (одним запросом на все topics)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)

    if topics:
        max_rows = db.execute(
            select(Parameter.topic, func.max(Reading.value_num))
            .join(Parameter, Parameter.id == Reading.parameter_id)
            .where(Parameter.topic.in_(topics))
            .where(Reading.ts >= start)
            .where(Reading.ts <= end)
            .group_by(Parameter.topic)
        ).all()
    else:
        max_rows = []

    max_map = {t: (mx if mx is None else float(mx)) for (t, mx) in max_rows}

    out: list[LinePowerOut] = []
    for ui_id in ui_ids:
        led_topic = topic_by.get((ui_id, "led.power"))
        hps_topic = topic_by.get((ui_id, "hps.power"))

        led_now = last_num(led_topic)
        hps_now = last_num(hps_topic)

        cfg = cfg_map.get(ui_id)
        led_nom = cfg.led_nominal_w if cfg else None
        led_cnt = cfg.led_lamps_count if cfg else None
        hps_nom = cfg.hps_nominal_w if cfg else None
        hps_cnt = cfg.hps_lamps_count if cfg else None

        led_max = max_map.get(led_topic) if led_topic else None
        hps_max = max_map.get(hps_topic) if hps_topic else None

        def calc_pct(now: float | None, nom: int | None) -> float | None:
            if now is None or nom is None or nom <= 0:
                return None
            return max(0.0, (now / float(nom)) * 100.0)

        def calc_not_burning(pct: float | None, cnt: int | None) -> int | None:
            if pct is None or cnt is None or cnt <= 0:
                return None
            miss = (1.0 - pct / 100.0) * float(cnt)
            # округляем к ближайшему целому
            return int(round(max(0.0, miss)))

        led_pct = calc_pct(led_now, led_nom)
        hps_pct = calc_pct(hps_now, hps_nom)

        out.append(
            LinePowerOut(
                ui_id=ui_id,
                led_power_now=led_now,
                hps_power_now=hps_now,
                led_nominal_w=led_nom,
                led_lamps_count=led_cnt,
                hps_nominal_w=hps_nom,
                hps_lamps_count=hps_cnt,
                led_max_24h=led_max,
                hps_max_24h=hps_max,
                led_burn_pct=led_pct,
                hps_burn_pct=hps_pct,
                led_not_burning=calc_not_burning(led_pct, led_cnt),
                hps_not_burning=calc_not_burning(hps_pct, hps_cnt),
            )
        )

    return out

@router.post("/line/{ui_id}/config", dependencies=[Depends(require_token)])
def set_line_power_config(ui_id: str, payload: LinePowerConfigIn, db: Session = Depends(get_db)):
    power_crud.upsert_config(
        db,
        ui_id=ui_id,
        led_nominal_w=payload.led_nominal_w,
        led_lamps_count=payload.led_lamps_count,
        hps_nominal_w=payload.hps_nominal_w,
        hps_lamps_count=payload.hps_lamps_count,
    )
    db.commit()
    return {"ok": True}