# app/api/v1/routes_cabinets.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.auth import require_token

from app.api.v1.schemas_cabinets import (
    CabinetOut, CabinetSnapshotOut, CabinetBindingOut, CabinetLineOut, LastValue
)
from app.db.models import Parameter, ParameterLast
from app.db.models_sources import SourceBinding
from app.db import source_crud

from pydantic import BaseModel

router = APIRouter(prefix="/cabinets", tags=["cabinets"])


@router.get("", response_model=list[CabinetOut])
def list_cabinets(db: Session = Depends(get_db)):
    sources = source_crud.list_sources(db)

    # быстро считаем members_count пачкой
    # (простым способом — для начала; если захочешь, оптимизируем join+group)
    out: list[CabinetOut] = []
    for s in sources:
        members = source_crud.list_source_members(db, s.source_id)
        out.append(
            CabinetOut(
                source_id=s.source_id,
                title=getattr(s, "title", None),
                manual_topic=getattr(s, "manual_topic", None),
                meta=getattr(s, "meta", None),
                members_count=len(members),
            )
        )
    return out


@router.get("/{source_id}/snapshot", response_model=CabinetSnapshotOut)
def cabinet_snapshot(
    source_id: str,
    include_line_bindings: bool = Query(default=True, description="Если False — отдаём только last по линиям без bind_key"),
    db: Session = Depends(get_db),
):
    src = source_crud.get_source(db, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Cabinet not found")

    ui_ids = source_crud.list_source_members(db, source_id)
    elements = source_crud.get_elements(db, ui_ids)
    el_map = {e.ui_id: e for e in elements}

    # 1) bindings щита
    sb = source_crud.list_source_bindings(db, source_id)
    cabinet_topics = [b.topic for b in sb if b.topic]

    # 2) line bindings (mqtt) -> topics
    line_bindings = source_crud.get_line_bindings_for_ui_ids(db, ui_ids) if include_line_bindings else []
    line_topics = [t for (_, _, t) in line_bindings if t]

    # 3) last по всем topics одним запросом
    all_topics = list({*cabinet_topics, *line_topics})
    last_map: dict[str, tuple] = {}
    if all_topics:
        rows = db.execute(
            select(
                Parameter.topic,
                ParameterLast.ts,
                ParameterLast.status_code,
                ParameterLast.status_message,
                ParameterLast.silent_for_s,
                ParameterLast.value_num,
                ParameterLast.value_text,
            )
            .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
            .where(Parameter.topic.in_(all_topics))
        ).all()

        last_map = {
            topic: (ts, sc, sm, silent, vn, vt)
            for (topic, ts, sc, sm, silent, vn, vt) in rows
        }

    def mk_last(topic: str) -> LastValue | None:
        t = last_map.get(topic)
        if not t:
            return None
        ts, sc, sm, silent, vn, vt = t
        return LastValue(
            topic=topic,
            ts=ts,
            status_code=sc,
            status_message=sm,
            silent_for_s=silent,
            value_num=(float(vn) if vn is not None else None),
            value_text=vt,
        )

    # 4) cabinet_values
    cabinet_values: list[CabinetBindingOut] = []
    for b in sb:
        cabinet_values.append(
            CabinetBindingOut(
                bind_key=b.bind_key,
                topic=b.topic,
                value_type=b.value_type,
                required=b.required,
                note=b.note,
                last=mk_last(b.topic),
            )
        )

    # 5) lines values
    # ui_id -> bind_key -> last
    line_val_map: dict[str, dict[str, LastValue]] = {}
    for ui_id, bind_key, topic in line_bindings:
        if not topic:
            continue
        lv = mk_last(topic)
        if lv is None:
            continue
        line_val_map.setdefault(ui_id, {})[bind_key] = lv

    lines: list[CabinetLineOut] = []
    for ui_id in ui_ids:
        e = el_map.get(ui_id)
        lines.append(
            CabinetLineOut(
                ui_id=ui_id,
                title=(e.title if e else None),
                cz=(getattr(e, "cz", None) if e else None),
                row_n=(getattr(e, "row_n", None) if e else None),
                col_n=(getattr(e, "col_n", None) if e else None),
                meta=(e.meta if e else None),
                values=line_val_map.get(ui_id, {}),
            )
        )

    cabinet = CabinetOut(
        source_id=src.source_id,
        title=getattr(src, "title", None),
        manual_topic=getattr(src, "manual_topic", None),
        meta=getattr(src, "meta", None),
        members_count=len(ui_ids),
    )

    return CabinetSnapshotOut(
        cabinet=cabinet,
        cabinet_values=cabinet_values,
        lines=lines,
    )

# app/api/v1/routes_cabinets.py  (ниже)
@router.get("/{source_id}/bindings", response_model=list[CabinetBindingOut])
def list_cabinet_bindings(source_id: str, db: Session = Depends(get_db)):
    src = source_crud.get_source(db, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Cabinet not found")

    sb = source_crud.list_source_bindings(db, source_id)
    return [
        CabinetBindingOut(
            bind_key=b.bind_key,
            topic=b.topic,
            value_type=b.value_type,
            required=b.required,
            note=b.note,
            last=None,
        )
        for b in sb
    ]


@router.post("/{source_id}/bindings", dependencies=[Depends(require_token)])
def upsert_cabinet_binding(source_id: str, payload: SourceBindingIn, db: Session = Depends(get_db)):
    src = source_crud.get_source(db, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Cabinet not found")

    source_crud.upsert_source_binding(
        db,
        source_id=source_id,
        bind_key=payload.bind_key,
        topic=payload.topic,
        value_type=payload.value_type,
        required=payload.required,
        note=payload.note,
    )
    db.commit()
    return {"ok": True}


class SourceBindingIn(BaseModel):
    bind_key: str
    topic: str
    value_type: str | None = None
    required: bool = False
    note: str | None = None