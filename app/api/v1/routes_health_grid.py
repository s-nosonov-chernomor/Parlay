# app/api/v1/routes_health_grid.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas_health import CabinetHealthCell
from app.db.models import Parameter, ParameterLast
from app.db.models_ui import UiHwSource
from app.db.models_sources import SourceBinding
from app.settings import get_settings
settings = get_settings()

router = APIRouter(prefix="/cabinets/health", tags=["health"])


def _meta_get_int(meta: dict | None, *keys: str) -> int | None:
    if not meta:
        return None
    for k in keys:
        v = meta.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except Exception:
            continue
    return None


@router.get("/grid", response_model=list[CabinetHealthCell])
def cabinets_health_grid(
    include_optional: bool = Query(default=True, description="Если false — мониторим только required=true из source_bindings (+manual_topic)"),
    db: Session = Depends(get_db),
):
    """
    Возвращает "шахматку" щитов (UiHwSource) со статусом по их общим параметрам.
    Источники данных:
      - source_bindings для каждого source_id
      - manual_topic из ui_hw_sources (если включено HEALTH_INCLUDE_MANUAL_TOPIC)
      - last значения из parameter_last
    """

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=settings.HEALTH_STALE_S)

    # 1) Все щиты
    sources: list[UiHwSource] = db.execute(
        select(UiHwSource).order_by(UiHwSource.source_id.asc())
    ).scalars().all()

    if not sources:
        return []

    source_ids = [s.source_id for s in sources]

    # 2) Все source_bindings пачкой
    sb_rows: list[SourceBinding] = db.execute(
        select(SourceBinding).where(SourceBinding.source_id.in_(source_ids))
    ).scalars().all()

    # source_id -> list[binding]
    sb_by_source: dict[str, list[SourceBinding]] = {}
    for b in sb_rows:
        if not include_optional and not b.required:
            continue
        sb_by_source.setdefault(b.source_id, []).append(b)

    # 3) Собираем topics для last-значений (одним запросом)
    topics: set[str] = set()
    for s in sources:
        for b in sb_by_source.get(s.source_id, []):
            if b.topic:
                topics.add(b.topic)
        if settings.HEALTH_INCLUDE_MANUAL_TOPIC:
            mt = getattr(s, "manual_topic", None)
            if mt:
                topics.add(mt)

    last_map: dict[str, tuple] = {}
    if topics:
        rows = db.execute(
            select(
                Parameter.topic,
                ParameterLast.ts,
                ParameterLast.status_code,
                ParameterLast.status_message,
                ParameterLast.silent_for_s,
            )
            .join(ParameterLast, ParameterLast.parameter_id == Parameter.id)
            .where(Parameter.topic.in_(list(topics)))
        ).all()

        last_map = {
            topic: (ts, sc, sm, silent)
            for (topic, ts, sc, sm, silent) in rows
        }

    def eval_topic(topic: str) -> tuple[str, str | None]:
        """
        Возвращает severity ("ok"|"warn"|"crit"|"stale"|"missing") и reason.
        """
        rec = last_map.get(topic)
        if not rec:
            return "missing", "no_last"
        ts, sc, sm, silent = rec

        # stale
        if ts is None or ts < stale_before:
            return "stale", "stale_ts"

        # status_code
        if sc is not None and int(sc) != 0:
            return "crit", f"status_code={sc}"

        # silent_for_s
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

    out: list[CabinetHealthCell] = []

    for s in sources:
        meta: dict[str, Any] | None = getattr(s, "meta", None)
        title = getattr(s, "title", None)

        monitored_topics: list[str] = []

        # source_bindings
        for b in sb_by_source.get(s.source_id, []):
            if b.topic:
                monitored_topics.append(b.topic)

        # manual topic
        if settings.HEALTH_INCLUDE_MANUAL_TOPIC:
            mt = getattr(s, "manual_topic", None)
            if mt:
                monitored_topics.append(mt)

        monitored_topics = list(dict.fromkeys(monitored_topics))  # уникальные, сохраняем порядок

        # считаем метрики
        bad_status_count = 0
        silent_warn_count = 0
        silent_crit_count = 0
        stale_count = 0

        last_updated_at: datetime | None = None

        worst_topic: str | None = None
        worst_reason: str | None = None
        worst_rank = -1  # ok=0 warn=1 stale=2 crit=3 missing=4 (missing считаем хуже stale)

        def rank(sev: str) -> int:
            return {"ok": 0, "warn": 1, "stale": 2, "crit": 3, "missing": 4}.get(sev, 0)

        for t in monitored_topics:
            sev, reason = eval_topic(t)

            rec = last_map.get(t)
            if rec:
                ts, _, _, _ = rec
                if ts and (last_updated_at is None or ts > last_updated_at):
                    last_updated_at = ts

            if sev == "crit":
                # уточним что именно критично (status_code / silent_crit)
                rec2 = last_map.get(t)
                if rec2:
                    _, sc, _, silent = rec2
                    if sc is not None and int(sc) != 0:
                        bad_status_count += 1
                    else:
                        # значит silent_crit
                        silent_crit_count += 1
                else:
                    bad_status_count += 1

            elif sev == "warn":
                silent_warn_count += 1
            elif sev == "stale":
                stale_count += 1
            elif sev == "missing":
                stale_count += 1  # для шахматки missing считаем как "stale/нет данных"

            r = rank(sev)
            if r > worst_rank:
                worst_rank = r
                worst_topic = t
                worst_reason = reason

        # итоговый статус
        if not monitored_topics:
            status = "unknown"
        elif bad_status_count > 0 or silent_crit_count > 0:
            status = "red"
        elif stale_count > 0:
            status = "red"  # на гриде лучше красным: нет данных/просрочено
        elif silent_warn_count > 0:
            status = "yellow"
        else:
            status = "green"

        out.append(
            CabinetHealthCell(
                source_id=s.source_id,
                title=title,

                cz=_meta_get_int(meta, "cz", "zone", "climate_zone"),
                row_n=_meta_get_int(meta, "row_n", "row", "rowNum"),
                col_n=_meta_get_int(meta, "col_n", "col", "colNum"),
                x=_meta_get_int(meta, "x"),
                y=_meta_get_int(meta, "y"),

                status=status,
                last_updated_at=last_updated_at,

                monitored_topics=len(monitored_topics),
                bad_status_count=bad_status_count,
                silent_warn_count=silent_warn_count,
                silent_crit_count=silent_crit_count,
                stale_count=stale_count,

                worst_topic=worst_topic,
                worst_reason=worst_reason,
            )
        )

    return out
