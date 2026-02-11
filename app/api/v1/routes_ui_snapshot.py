# app/api/v1/routes_ui_snapshot.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas_ui_snapshot import (
    UiSnapshotOut, UiElementOut, UiBindingOut, UiStateOut, TopicLastOut
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
    )
