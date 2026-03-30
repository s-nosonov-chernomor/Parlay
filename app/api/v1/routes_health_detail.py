from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_authenticated
from app.api.v1.schemas_health_detail import CabinetHealthDetail, HealthTopicIssue, LineHealth
from app.db.models import Parameter, ParameterLast
from app.db.models_ui import UiHwSource, UiElement, UiBinding, UiHwMember
from app.db.models_sources import SourceBinding
from app.settings import get_settings

settings = get_settings()

router = APIRouter(prefix="/cabinets/health", tags=["health"])


def _coerce_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _rank_issue(sev: str) -> int:
    return {"ok": 0, "warn": 1, "stale": 2, "crit": 3, "missing": 4, "alarm": 5}.get(sev, 0)


@router.get("/{source_id}", response_model=CabinetHealthDetail)
def cabinet_health_detail(
    source_id: str,
    include_optional: bool = Query(
        default=True,
        description="Если false — мониторим только required=true из source_bindings (+manual_topic)",
    ),
    include_lines: bool = Query(
        default=True,
        description="Посчитать health по линиям щита",
    ),
    current_user=Depends(require_authenticated),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=settings.HEALTH_STALE_S)

    src: UiHwSource | None = db.execute(
        select(UiHwSource).where(UiHwSource.source_id == source_id)
    ).scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=404, detail="Cabinet not found")

    title = getattr(src, "title", None)
    manual_topic = getattr(src, "manual_topic", None) if settings.HEALTH_INCLUDE_MANUAL_TOPIC else None

    # --- source_bindings ---
    sb: list[SourceBinding] = db.execute(
        select(SourceBinding).where(SourceBinding.source_id == source_id)
    ).scalars().all()
    if not include_optional:
        sb = [b for b in sb if b.required]

    cabinet_topics: list[tuple[str, str | None]] = []
    for b in sb:
        if b.topic:
            cabinet_topics.append((b.topic, b.bind_key))
    if manual_topic:
        cabinet_topics.append((manual_topic, "manual"))

    unique_topics = list(dict.fromkeys([t for (t, _) in cabinet_topics]))

    # --- last по topics щита ---
    last_map: dict[str, tuple] = {}
    if unique_topics:
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
            .where(Parameter.topic.in_(unique_topics))
        ).all()
        last_map = {
            topic: (ts, sc, sm, silent, vn, vt)
            for (topic, ts, sc, sm, silent, vn, vt) in rows
        }

    def eval_issue(topic: str) -> tuple[str, str | None]:
        rec = last_map.get(topic)
        if not rec:
            return "missing", "no_last"
        ts, sc, sm, silent, vn, vt = rec

        if ts is None or ts < stale_before:
            return "stale", "stale_ts"

        if sc is not None and int(sc) != 0:
            return "crit", f"status_code={sc}"

        if silent is not None:
            try:
                s_val = int(silent)
            except Exception:
                s_val = None
            if s_val is not None:
                if s_val >= settings.HEALTH_SILENT_CRIT_S:
                    return "crit", f"silent_for_s>={settings.HEALTH_SILENT_CRIT_S}"
                if s_val >= settings.HEALTH_SILENT_WARN_S:
                    return "warn", f"silent_for_s>={settings.HEALTH_SILENT_WARN_S}"

        return "ok", None

    issues: list[HealthTopicIssue] = []
    worst_sev = "ok"
    worst_rank = -1
    worst_ts: datetime | None = None

    manual_switch_alarm = False

    if manual_topic:
        rec = last_map.get(manual_topic)
        if rec:
            _, _, _, _, vn, vt = rec
            v = _coerce_float(vn)
            if v is None and vt is not None:
                v = _coerce_float(vt)
            if v is not None and int(v) == 0:
                manual_switch_alarm = True

    for topic, bind_key in cabinet_topics:
        rec = last_map.get(topic)
        ts = sc = sm = silent = vn = vt = None
        if rec:
            ts, sc, sm, silent, vn, vt = rec
            if worst_ts is None or (ts and ts > worst_ts):
                worst_ts = ts

        sev, reason = eval_issue(topic)

        if bind_key == "manual" and manual_switch_alarm:
            sev, reason = "alarm", "manual_switch_off"

        r = _rank_issue(sev)
        if r > worst_rank:
            worst_rank = r
            worst_sev = sev

        issues.append(
            HealthTopicIssue(
                topic=topic,
                bind_key=bind_key,
                severity=sev,
                reason=reason,
                ts=ts,
                status_code=sc,
                status_message=sm,
                silent_for_s=silent,
                value_num=_coerce_float(vn),
                value_text=vt,
            )
        )

    if not unique_topics:
        status = "unknown"
    else:
        if worst_sev in ("alarm", "crit", "missing", "stale"):
            status = "red"
        elif worst_sev == "warn":
            status = "yellow"
        else:
            status = "green"

    # --- health по линиям ---
    members_count = 0
    lines_red = lines_yellow = lines_green = lines_unknown = 0
    worst_lines: list[LineHealth] = []

    if include_lines:
        ui_ids = [
            x for (x,) in db.execute(
                select(UiHwMember.ui_id).where(UiHwMember.source_id == source_id)
            ).all()
        ]
        members_count = len(ui_ids)

        if ui_ids:
            elements = db.execute(select(UiElement).where(UiElement.ui_id.in_(ui_ids))).scalars().all()
            el_map = {e.ui_id: e for e in elements}

            lb_rows = db.execute(
                select(UiBinding.ui_id, UiBinding.bind_key, UiBinding.topic)
                .where(UiBinding.ui_id.in_(ui_ids))
                .where(UiBinding.source == "mqtt")
            ).all()

            line_topics = list({t for (_, _, t) in lb_rows if t})
            line_last_map: dict[str, tuple] = {}
            if line_topics:
                rows2 = db.execute(
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
                    .where(Parameter.topic.in_(line_topics))
                ).all()
                line_last_map = {
                    topic: (ts, sc, sm, silent, vn, vt)
                    for (topic, ts, sc, sm, silent, vn, vt) in rows2
                }

            def eval_line_topic(topic: str) -> tuple[str, str | None]:
                rec = line_last_map.get(topic)
                if not rec:
                    return "missing", "no_last"
                ts, sc, sm, silent, vn, vt = rec
                if ts is None or ts < stale_before:
                    return "stale", "stale_ts"
                if sc is not None and int(sc) != 0:
                    return "crit", f"status_code={sc}"
                if silent is not None:
                    try:
                        s_val = int(silent)
                    except Exception:
                        s_val = None
                    if s_val is not None:
                        if s_val >= settings.HEALTH_SILENT_CRIT_S:
                            return "crit", f"silent_for_s>={settings.HEALTH_SILENT_CRIT_S}"
                        if s_val >= settings.HEALTH_SILENT_WARN_S:
                            return "warn", f"silent_for_s>={settings.HEALTH_SILENT_WARN_S}"
                return "ok", None

            by_ui: dict[str, list[str]] = {}
            for ui_id, _, topic in lb_rows:
                if topic:
                    by_ui.setdefault(ui_id, []).append(topic)

            for ui_id in ui_ids:
                topics = list(dict.fromkeys(by_ui.get(ui_id, [])))
                if not topics:
                    lines_unknown += 1
                    continue

                worst_r = -1
                worst_topic = None
                worst_reason = None
                bad = 0

                for t in topics:
                    sev, reason = eval_line_topic(t)
                    r = _rank_issue(sev)
                    if sev in ("crit", "missing", "stale"):
                        bad += 1
                    if r > worst_r:
                        worst_r = r
                        worst_topic = t
                        worst_reason = reason

                if worst_r <= _rank_issue("ok"):
                    sev_line = "green"
                    lines_green += 1
                elif worst_r <= _rank_issue("warn"):
                    sev_line = "yellow"
                    lines_yellow += 1
                else:
                    sev_line = "red"
                    lines_red += 1

                e = el_map.get(ui_id)
                worst_lines.append(
                    LineHealth(
                        ui_id=ui_id,
                        title=(e.title if e else None),
                        severity=sev_line,
                        bad_topics=bad,
                        worst_topic=worst_topic,
                        worst_reason=worst_reason,
                    )
                )

            worst_lines.sort(
                key=lambda x: (
                    {"red": 2, "yellow": 1, "green": 0, "unknown": -1}.get(x.severity, 0),
                    x.bad_topics,
                ),
                reverse=True,
            )
            worst_lines = worst_lines[:3]

    return CabinetHealthDetail(
        source_id=src.source_id,
        title=title,
        status=status,
        last_updated_at=worst_ts,
        manual_topic=manual_topic,
        manual_switch_alarm=manual_switch_alarm,
        monitored_topics=len(unique_topics),
        issues=issues,
        members_count=members_count,
        lines_red=lines_red,
        lines_yellow=lines_yellow,
        lines_green=lines_green,
        lines_unknown=lines_unknown,
        worst_lines=worst_lines,
    )