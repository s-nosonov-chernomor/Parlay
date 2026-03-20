# app/api/v1/routes_ui_par_dli.py

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas_par_dli import (
    UiParDliConfigIn,
    UiParDliConfigOut,
    UiParDliStateOut,
)
from app.db import par_dli_crud


router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/{ui_id}/par-dli", response_model=UiParDliConfigOut)
def get_par_dli_config(ui_id: str, db: Session = Depends(get_db)):
    cfg = par_dli_crud.load_config(db, ui_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="PAR_DLI config not found")

    return UiParDliConfigOut(
        ui_id=cfg.ui_id,
        start_time=cfg.start_time,
        par_target_umol=cfg.par_target_umol,
        par_deadband_umol=cfg.par_deadband_umol,
        dli_target_mol=cfg.dli_target_mol,
        off_window_start=cfg.off_window_start,
        off_window_end=cfg.off_window_end,
        fixture_umol_100=cfg.fixture_umol_100,
        correction_interval_s=cfg.correction_interval_s,
        par_top_bind_key=cfg.par_top_bind_key,
        par_sum_bind_key=cfg.par_sum_bind_key,
        enabled_bind_key=cfg.enabled_bind_key,
        dim_bind_key=cfg.dim_bind_key,
        use_capped_dli=cfg.use_capped_dli,
        tz=cfg.tz,
        updated_at=cfg.updated_at,
    )


@router.put("/{ui_id}/par-dli", response_model=UiParDliConfigOut)
def put_par_dli_config(ui_id: str, payload: UiParDliConfigIn, db: Session = Depends(get_db)):
    if not par_dli_crud.ui_exists(db, ui_id):
        raise HTTPException(status_code=404, detail="ui_id not found")

    updated_at = par_dli_crud.upsert_config(db, ui_id, payload)
    db.commit()

    return UiParDliConfigOut(
        ui_id=ui_id,
        start_time=payload.start_time,
        par_target_umol=payload.par_target_umol,
        par_deadband_umol=payload.par_deadband_umol,
        dli_target_mol=payload.dli_target_mol,
        off_window_start=payload.off_window_start,
        off_window_end=payload.off_window_end,
        fixture_umol_100=payload.fixture_umol_100,
        correction_interval_s=payload.correction_interval_s,
        par_top_bind_key=payload.par_top_bind_key,
        par_sum_bind_key=payload.par_sum_bind_key,
        enabled_bind_key=payload.enabled_bind_key,
        dim_bind_key=payload.dim_bind_key,
        use_capped_dli=payload.use_capped_dli,
        tz=payload.tz,
        updated_at=updated_at,
    )


@router.get("/{ui_id}/par-dli/state", response_model=UiParDliStateOut)
def get_par_dli_state(ui_id: str, db: Session = Depends(get_db)):
    st = par_dli_crud.load_state(db, ui_id)
    if not st:
        raise HTTPException(status_code=404, detail="PAR_DLI state not found")

    cfg = par_dli_crud.load_config(db, ui_id)

    par_top_current = None
    par_sum_current = None
    progress_pct = None

    if cfg:
        bindings = par_dli_crud.load_mqtt_bindings(
            db,
            ui_id,
            [cfg.par_top_bind_key, cfg.par_sum_bind_key],
        )
        topics = [b.topic for b in bindings.values()]
        last = par_dli_crud.load_last_values(db, topics)

        b1 = bindings.get(cfg.par_top_bind_key)
        if b1:
            vnum, _vtxt, _ts = last.get(b1.topic, (None, None, None))
            par_top_current = float(vnum) if vnum is not None else None

        b2 = bindings.get(cfg.par_sum_bind_key)
        if b2:
            vnum, _vtxt, _ts = last.get(b2.topic, (None, None, None))
            par_sum_current = float(vnum) if vnum is not None else None

        if cfg.dli_target_mol > 0:
            base = st.dli_capped_mol if cfg.use_capped_dli else st.dli_raw_mol
            progress_pct = max(0.0, min(100.0, base / cfg.dli_target_mol * 100.0))

    return UiParDliStateOut(
        ui_id=st.ui_id,
        local_date=st.local_date,
        dli_raw_mol=st.dli_raw_mol,
        dli_capped_mol=st.dli_capped_mol,
        last_calc_ts=st.last_calc_ts,
        last_sum_par_umol=st.last_sum_par_umol,
        last_control_ts=st.last_control_ts,
        last_pwm_pct=st.last_pwm_pct,
        last_enabled=st.last_enabled,
        target_reached_at=st.target_reached_at,
        forced_off=st.forced_off,
        updated_at=st.updated_at,
        par_top_current=par_top_current,
        par_sum_current=par_sum_current,
        progress_pct=progress_pct,
    )