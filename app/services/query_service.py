from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.db.models import Parameter, Reading
from app.db.models_ui import UiElement, UiBinding, UiHwMember
from app.db.models_sources import SourceBinding
from app.db import par_dli_crud


@dataclass(frozen=True, slots=True)
class ResolvedBinding:
    ui_id: str
    source_id: str | None
    zone_code: str | None
    bind_key: str
    note: str | None
    topic: str


class QueryService:
    def __init__(self) -> None:
        pass

    def _load_ui_meta(self, db: Session, ui_ids: list[str]) -> dict[str, dict]:
        rows = db.execute(
            select(UiElement.ui_id, UiElement.meta)
            .where(UiElement.ui_id.in_(ui_ids))
        ).all()
        out: dict[str, dict] = {}
        for ui_id, meta in rows:
            out[ui_id] = meta or {}
        return out

    def _load_membership(self, db: Session, ui_ids: list[str]) -> dict[str, str]:
        rows = db.execute(
            select(UiHwMember.ui_id, UiHwMember.source_id)
            .where(UiHwMember.ui_id.in_(ui_ids))
        ).all()
        return {ui_id: source_id for ui_id, source_id in rows}

    def resolve_bindings(self, db: Session, ui_ids: list[str], bind_keys: list[str]) -> list[ResolvedBinding]:
        """
        На каждый ui_id + bind_key возвращает конкретный topic.
        bind_key ищем:
          1) ui_bindings (source='line')
          2) source_bindings (через ui_hw_members -> source_id)
        """
        ui_meta = self._load_ui_meta(db, ui_ids)
        ui_to_source = self._load_membership(db, ui_ids)

        line_rows = db.execute(
            select(UiBinding.ui_id, UiBinding.bind_key, UiBinding.topic, UiBinding.note)
            .where(
                UiBinding.ui_id.in_(ui_ids),
                UiBinding.bind_key.in_(bind_keys),
                UiBinding.topic.is_not(None),
            )
        ).all()

        line_map: dict[tuple[str, str], tuple[str, str | None]] = {}
        for ui_id, bk, topic, note in line_rows:
            if topic:
                line_map[(ui_id, bk)] = (topic, note)

        source_ids = sorted(set(ui_to_source.values()))
        source_rows = db.execute(
            select(SourceBinding.source_id, SourceBinding.bind_key, SourceBinding.topic, SourceBinding.note)
            .where(
                and_(
                    SourceBinding.source_id.in_(source_ids),
                    SourceBinding.bind_key.in_(bind_keys),
                )
            )
        ).all()
        source_map: dict[tuple[str, str], tuple[str, str | None]] = {}
        for source_id, bk, topic, note in source_rows:
            source_map[(source_id, bk)] = (topic, note)

        resolved: list[ResolvedBinding] = []
        for ui_id in ui_ids:
            source_id = ui_to_source.get(ui_id)
            zone_code = (ui_meta.get(ui_id) or {}).get("zone_code")
            for bk in bind_keys:
                topic: str | None = None
                note: str | None = None

                lt = line_map.get((ui_id, bk))
                if lt:
                    topic, note = lt
                else:
                    if source_id:
                        st = source_map.get((source_id, bk))
                        if st:
                            topic, note = st

                if not topic:
                    continue

                resolved.append(
                    ResolvedBinding(
                        ui_id=ui_id,
                        source_id=source_id,
                        zone_code=zone_code,
                        bind_key=bk,
                        note=note,
                        topic=topic,
                    )
                )
        return resolved

    def resolve_one_binding(self, db: Session, ui_id: str, bind_key: str) -> ResolvedBinding | None:
        resolved = self.resolve_bindings(db, [ui_id], [bind_key])
        if not resolved:
            return None
        return resolved[0]

    def calc_dli(
        self,
        db: Session,
        ui_ids: list[str],
        dli_bind_key: str,
        start: datetime,
        end: datetime,
        mode: str,
        agro_day_start_time: time | None,
        dli_cap_umol: float | None,
        limit: int,
    ) -> tuple[list[dict], dict]:
        if not ui_ids:
            return [], {"requested_ui_ids": 0, "resolved": 0}

        ui_meta = self._load_ui_meta(db, ui_ids)
        ui_to_source = self._load_membership(db, ui_ids)

        rows_out: list[dict] = []
        resolved_count = 0

        for ui_id in ui_ids:
            resolved = self.resolve_one_binding(db, ui_id, dli_bind_key)
            if not resolved:
                continue

            series = par_dli_crud.calc_dli_series_for_topic(
                session=db,
                topic=resolved.topic,
                start_ts=start,
                end_ts=end,
                cap_umol=dli_cap_umol,
                mode=mode,
                tz_name="Europe/Riga",
                agro_day_start_time=agro_day_start_time,
            )

            for ts, raw_dli_mol, capped_dli_mol in series:
                rows_out.append(
                    dict(
                        ts=ts,
                        ui_id=ui_id,
                        source_id=ui_to_source.get(ui_id),
                        zone_code=(ui_meta.get(ui_id) or {}).get("zone_code"),
                        bind_key=dli_bind_key,
                        topic=resolved.topic,
                        raw_dli_mol=float(raw_dli_mol),
                        capped_dli_mol=float(capped_dli_mol),
                    )
                )

            resolved_count += 1

        rows_out.sort(key=lambda x: (x["ui_id"], x["ts"]))

        if limit and limit > 0:
            rows_out = rows_out[:limit]

        meta = {
            "requested_ui_ids": len(ui_ids),
            "resolved": resolved_count,
            "dli_bind_key": dli_bind_key,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "mode": mode,
            "agro_day_start_time": agro_day_start_time.isoformat() if agro_day_start_time else None,
            "dli_cap_umol": dli_cap_umol,
            "limit": limit,
        }
        return rows_out, meta

    def run(
        self,
        db: Session,
        ui_ids: list[str],
        bind_keys: list[str],
        start: datetime,
        end: datetime,
        bucket_s: int | None,
        limit: int,
    ) -> tuple[list[dict], dict]:
        resolved = self.resolve_bindings(db, ui_ids, bind_keys)
        if not resolved:
            return [], {"resolved": 0, "topics": []}

        topics = sorted({r.topic for r in resolved})

        pid_rows = db.execute(
            select(Parameter.topic, Parameter.id).where(Parameter.topic.in_(topics))
        ).all()
        topic_to_pid = {t: pid for t, pid in pid_rows}

        resolved = [r for r in resolved if r.topic in topic_to_pid]
        if not resolved:
            return [], {"resolved": 0, "topics": topics}

        pid_to_meta: dict[int, ResolvedBinding] = {}
        for r in resolved:
            pid = int(topic_to_pid[r.topic])

        pid_to_list: dict[int, list[ResolvedBinding]] = {}
        for r in resolved:
            pid = int(topic_to_pid[r.topic])
            pid_to_list.setdefault(pid, []).append(r)

        pids = sorted(pid_to_list.keys())

        rows_out: list[dict] = []

        if bucket_s and bucket_s > 0:
            bucket = func.to_timestamp(
                (
                    func.floor(
                        (
                            func.extract("epoch", Reading.ts)
                            - func.extract("epoch", start)
                        ) / float(bucket_s)
                    ) * float(bucket_s)
                ) + func.extract("epoch", start)
            )

            q = (
                select(
                    Reading.parameter_id,
                    bucket.label("ts"),
                    func.avg(Reading.value_num).label("value_num"),
                    func.max(Reading.value_text).label("value_text"),
                )
                .where(
                    and_(
                        Reading.parameter_id.in_(pids),
                        Reading.ts >= start,
                        Reading.ts <= end,
                    )
                )
                .group_by(Reading.parameter_id, bucket)
                .order_by(bucket.asc())
                .limit(limit)
            )

            data = db.execute(q).all()
            for pid, ts, vnum, vtext in data:
                for meta in pid_to_list.get(int(pid), []):
                    rows_out.append(
                        dict(
                            ts=ts,
                            ui_id=meta.ui_id,
                            source_id=meta.source_id,
                            zone_code=meta.zone_code,
                            bind_key=meta.bind_key,
                            note=meta.note,
                            topic=meta.topic,
                            value_num=float(vnum) if vnum is not None else None,
                            value_text=vtext,
                        )
                    )

        else:
            q = (
                select(
                    Reading.parameter_id,
                    Reading.ts,
                    Reading.value_num,
                    Reading.value_text,
                )
                .where(
                    and_(
                        Reading.parameter_id.in_(pids),
                        Reading.ts >= start,
                        Reading.ts <= end,
                    )
                )
                .order_by(Reading.ts.asc())
                .limit(limit)
            )
            data = db.execute(q).all()
            for pid, ts, vnum, vtext in data:
                for meta in pid_to_list.get(int(pid), []):
                    rows_out.append(
                        dict(
                            ts=ts,
                            ui_id=meta.ui_id,
                            source_id=meta.source_id,
                            zone_code=meta.zone_code,
                            bind_key=meta.bind_key,
                            note=meta.note,
                            topic=meta.topic,
                            value_num=vnum,
                            value_text=vtext,
                        )
                    )

        meta = {
            "requested_ui_ids": len(ui_ids),
            "requested_bind_keys": len(bind_keys),
            "resolved_bindings": len(resolved),
            "unique_topics": len(topics),
            "bucket_s": bucket_s,
            "limit": limit,
        }
        return rows_out, meta