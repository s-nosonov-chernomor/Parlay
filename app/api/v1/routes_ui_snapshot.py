from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas_ui_snapshot import (
    UiSnapshotOut,
    UiElementOut,
    UiBindingOut,
    UiStateOut,
    TopicLastOut,
    UiParDliConfigSnapOut,
    UiParDliStateSnapOut,
)
from app.db import ui_snapshot_crud as crud


router = APIRouter(prefix="/ui/page", tags=["ui"])


@router.get("/{page}/snapshot", response_model=UiSnapshotOut)
def page_snapshot(page: str, db: Session = Depends(get_db)):
    elements = crud.load_elements(db, page)
    ui_ids = [e.ui_id for e in elements]

    bindings = crud.load_bindings(db, ui_ids)
    states_map = crud.load_states(db, ui_ids)
    manual_topic_by_ui = crud.load_manual_topics(db, ui_ids)

    par_dli_cfg_map = crud.load_par_dli_configs(db, ui_ids)
    par_dli_state_map = crud.load_par_dli_states(db, ui_ids)

    # topics to fetch last
    topics: set[str] = set()
    for b in bindings:
        if b.topic:
            topics.add(b.topic)
    for mt in manual_topic_by_ui.values():
        topics.add(mt)

    last_map = crud.load_last_by_topics(db, list(topics))

    # build states
    out_states: list[UiStateOut] = []
    for ui_id in ui_ids:
        st = states_map.get(ui_id)
        mode_req = st.mode_requested if st else None
        schedule_id = st.schedule_id if st else None

        manual_topic = manual_topic_by_ui.get(ui_id)
        manual_hw = False
        if manual_topic and manual_topic in last_map:
            ts, sc, sm, silent, vnum, vtxt = last_map[manual_topic]
            bit = crud._as_int01(vnum, vtxt)
            manual_hw = (bit is not None and bit == 0)

        mode_eff = crud.compute_state_effective(mode_req, manual_hw)

        out_states.append(
            UiStateOut(
                ui_id=ui_id,
                mode_requested=mode_req,
                mode_effective=mode_eff,
                schedule_id=schedule_id,
                manual_hw=manual_hw,
                manual_topic=manual_topic,
            )
        )

    out_par_dli_cfg: list[UiParDliConfigSnapOut] = []
    for ui_id in ui_ids:
        cfg = par_dli_cfg_map.get(ui_id)
        if not cfg:
            continue

        out_par_dli_cfg.append(
            UiParDliConfigSnapOut(
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
        )

    out_par_dli_state: list[UiParDliStateSnapOut] = []
    for ui_id in ui_ids:
        st = par_dli_state_map.get(ui_id)
        if not st:
            continue

        cfg = par_dli_cfg_map.get(ui_id)
        progress_pct = None
        if cfg and cfg.dli_target_mol > 0:
            base = st.dli_capped_mol if cfg.use_capped_dli else st.dli_raw_mol
            progress_pct = max(0.0, min(100.0, base / cfg.dli_target_mol * 100.0))

        out_par_dli_state.append(
            UiParDliStateSnapOut(
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
                progress_pct=progress_pct,
            )
        )

    return UiSnapshotOut(
        page=page,
        elements=[
            UiElementOut(
                ui_id=e.ui_id,
                ui_type=e.ui_type,
                page=e.page,
                title=e.title,
                cz=e.cz,
                row_n=e.row_n,
                col_n=e.col_n,
                meta=e.meta or {},
            )
            for e in elements
        ],
        bindings=[
            UiBindingOut(
                ui_id=b.ui_id,
                bind_key=b.bind_key,
                topic=b.topic,
                source=b.source,
                value_type=b.value_type,
                required=b.required,
                note=b.note,
            )
            for b in bindings
        ],
        states=out_states,
        last=[
            TopicLastOut(
                topic=topic,
                ts=vals[0],
                status_code=vals[1],
                status_message=vals[2],
                silent_for_s=vals[3],
                value_num=vals[4],
                value_text=vals[5],
            )
            for topic, vals in last_map.items()
        ],
        par_dli_configs=out_par_dli_cfg,
        par_dli_states=out_par_dli_state,
    )