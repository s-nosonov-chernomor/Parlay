# app/db/ui_crud.py
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Parameter, ParameterLast
from app.db.models_ui import (
    UiElement,
    UiBinding,
    UiElementState,
    UiHwSource,
    UiHwMember,
    UiPrivaBinding,
)


def _as_int01(value_num: float | None, value_text: str | None) -> int | None:
    if value_num is not None:
        return 0 if float(value_num) == 0.0 else 1
    if value_text is None:
        return None
    s = str(value_text).strip().lower()
    if s in {"0", "false", "off", "no"}:
        return 0
    if s in {"1", "true", "on", "yes"}:
        return 1
    return None


def load_ui_page(session: Session, page: str) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Возвращает:
      - elements: список dict (готовые элементы)
      - subscribe_topics: список mqtt-topics, которые фронту нужно слушать
        (только ui_bindings.source='mqtt' и topic not null)
    """
    elements = session.execute(
        select(UiElement).where(UiElement.page == page).order_by(UiElement.ui_id.asc())
    ).scalars().all()

    if not elements:
        return [], []

    ui_ids = [e.ui_id for e in elements]

    # bindings
    bindings = session.execute(
        select(UiBinding).where(UiBinding.ui_id.in_(ui_ids))
    ).scalars().all()

    bindings_by_ui: dict[str, list[UiBinding]] = defaultdict(list)

    subscribe_topics_set: set[str] = set()
    for b in bindings:
        bindings_by_ui[b.ui_id].append(b)
        if b.source == "mqtt" and b.topic:
            subscribe_topics_set.add(b.topic)

    # priva bindings
    priva_rows = session.execute(
        select(UiPrivaBinding).where(UiPrivaBinding.ui_id.in_(ui_ids))
    ).scalars().all()

    priva_by_ui: dict[str, list[UiPrivaBinding]] = defaultdict(list)
    for p in priva_rows:
        priva_by_ui[p.ui_id].append(p)

    # element state
    states = session.execute(
        select(UiElementState).where(UiElementState.ui_id.in_(ui_ids))
    ).scalars().all()

    state_by_ui: dict[str, UiElementState] = {s.ui_id: s for s in states}

    # ui_id -> manual_topic (hw)
    hw_map = session.execute(
        select(UiHwMember.ui_id, UiHwSource.manual_topic)
        .join(UiHwSource, UiHwSource.source_id == UiHwMember.source_id)
        .where(UiHwMember.ui_id.in_(ui_ids))
    ).all()

    manual_topic_by_ui: dict[str, str] = {}
    manual_topics: set[str] = set()
    for ui_id, manual_topic in hw_map:
        if manual_topic:
            manual_topic_by_ui[ui_id] = manual_topic
            manual_topics.add(manual_topic)

    # manual topics тоже полезно слушать фронту (чтобы alarm мигал мгновенно)
    subscribe_topics_set.update(manual_topics)

    manual_last_by_topic: dict[str, tuple[float | None, str | None]] = {}
    if manual_topics:
        rows = session.execute(
            select(Parameter.topic, ParameterLast.value_num, ParameterLast.value_text)
            .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
            .where(Parameter.topic.in_(list(manual_topics)))
        ).all()
        for topic, vnum, vtxt in rows:
            manual_last_by_topic[str(topic)] = (vnum, vtxt)

    out: list[dict[str, Any]] = []
    for e in elements:
        st = state_by_ui.get(e.ui_id)
        mode_requested = st.mode_requested if st else "WEB"
        schedule_id = st.schedule_id if st else None

        manual_topic = manual_topic_by_ui.get(e.ui_id)
        manual_hw = False
        if manual_topic:
            vnum, vtxt = manual_last_by_topic.get(manual_topic, (None, None))
            bit = _as_int01(vnum, vtxt)
            if bit is not None and bit == 0:
                manual_hw = True

        alarm = manual_hw
        mode_effective = "HW_MANUAL_BLOCK" if manual_hw else mode_requested

        out.append(
            dict(
                ui_id=e.ui_id,
                ui_type=e.ui_type,
                page=e.page,
                title=e.title,
                cz=e.cz,
                row_n=e.row_n,
                col_n=e.col_n,
                meta=e.meta or {},

                mode_requested=mode_requested,
                schedule_id=schedule_id,

                manual_hw=manual_hw,
                alarm=alarm,
                mode_effective=mode_effective,

                manual_topic=manual_topic,

                bindings=[
                    dict(
                        bind_key=b.bind_key,
                        source=b.source,
                        topic=b.topic,
                        value_type=b.value_type,
                        required=bool(b.required),
                        note=b.note,
                    )
                    for b in sorted(bindings_by_ui.get(e.ui_id, []), key=lambda x: x.bind_key)
                ],
                priva=[
                    dict(
                        bind_key=p.bind_key,
                        priva_topic=p.priva_topic,
                        note=p.note,
                    )
                    for p in sorted(priva_by_ui.get(e.ui_id, []), key=lambda x: x.bind_key)
                ],
            )
        )

    subscribe_topics = sorted(subscribe_topics_set)
    return out, subscribe_topics
