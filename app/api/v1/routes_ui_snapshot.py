from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_authenticated
from app.api.v1.schemas_ui_snapshot import (
    UiSnapshotOut,
    UiElementOut,
    UiBindingOut,
    UiStateOut,
    TopicLastOut,
    UiParDliConfigSnapOut,
)
from app.db import ui_snapshot_crud as crud


router = APIRouter(prefix="/ui/page", tags=["ui"])


@router.get("/{page}/snapshot", response_model=UiSnapshotOut)
def page_snapshot(page: str, current_user=Depends(require_authenticated), db: Session = Depends(get_db)):
    elements = crud.load_elements(db, page)
    ui_ids = [e.ui_id for e in elements]

    bindings = crud.load_bindings(db, ui_ids)
    states_map = crud.load_states(db, ui_ids)
    manual_topic_by_ui = crud.load_manual_topics(db, ui_ids)

    # topics to fetch last
    topics: set[str] = set()
    for b in bindings:
        if b.topic:
            topics.add(b.topic)
    for mt in manual_topic_by_ui.values():
        topics.add(mt)

    last_map = crud.load_last_by_topics(db, list(topics))

    # collect par_ids from ui states
    par_ids: list[str] = []
    for ui_id in ui_ids:
        st = states_map.get(ui_id)
        if st and st.par_id:
            par_ids.append(st.par_id)

    par_dli_cfg_map = crud.load_par_dli_configs_by_ids(db, par_ids)

    # build states
    out_states: list[UiStateOut] = []
    for ui_id in ui_ids:
        st = states_map.get(ui_id)
        mode_req = st.mode_requested if st else None
        schedule_id = st.schedule_id if st else None
        par_id = st.par_id if st else None

        manual_topic = manual_topic_by_ui.get(ui_id)
        manual_hw = False
        if manual_topic and manual_topic in last_map:
            _ts, _sc, _sm, _silent, vnum, vtxt = last_map[manual_topic]
            bit = crud._as_int01(vnum, vtxt)
            manual_hw = (bit is not None and bit == 0)

        mode_eff = crud.compute_state_effective(mode_req, manual_hw)

        out_states.append(
            UiStateOut(
                ui_id=ui_id,
                mode_requested=mode_req,
                mode_effective=mode_eff,
                schedule_id=schedule_id,
                par_id=par_id,
                manual_hw=manual_hw,
                manual_topic=manual_topic,
            )
        )

    out_par_dli_cfg: list[UiParDliConfigSnapOut] = []
    for par_id, cfg in par_dli_cfg_map.items():
        out_par_dli_cfg.append(
            UiParDliConfigSnapOut(
                par_id=cfg.par_id,
                title=cfg.title,
                start_time=cfg.start_time,
                ppfd_setpoint_umol=cfg.ppfd_setpoint_umol,
                par_deadband_umol=cfg.par_deadband_umol,
                dli_target_mol=cfg.dli_target_mol,
                dli_cap_umol=cfg.dli_cap_umol,
                off_window_start=cfg.off_window_start,
                off_window_end=cfg.off_window_end,
                fixture_umol_100=cfg.fixture_umol_100,
                correction_interval_s=cfg.correction_interval_s,
                par_top_bind_key=cfg.par_top_bind_key,
                par_sum_bind_key=cfg.par_sum_bind_key,
                enabled_bind_keys=cfg.enabled_bind_keys,
                dim_bind_keys=cfg.dim_bind_keys,
                use_dli_cap=cfg.use_dli_cap,
                tz=cfg.tz,
                updated_at=cfg.updated_at,
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
    )