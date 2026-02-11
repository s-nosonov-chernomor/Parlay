# app/mqtt/parser.py

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import orjson


@dataclass(slots=True)
class ParsedMessage:
    topic: str
    ts: datetime
    trigger: str | None
    status_source: str | None
    status_code: int | None
    status_message: str | None
    silent_for_s: int | None
    value_num: float | None
    value_text: str | None
    raw: dict | None


def _parse_iso_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Persay присылает Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _try_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        vv = v.strip()
        if vv == "":
            return None
        try:
            return float(vv.replace(",", "."))
        except Exception:
            return None
    return None


def parse_mqtt_payload(topic: str, payload_bytes: bytes) -> ParsedMessage:
    now = datetime.now(timezone.utc)

    # 1) Быстрый путь: пробуем orjson как JSON
    raw_obj: dict | None = None
    try:
        obj = orjson.loads(payload_bytes)
        if isinstance(obj, dict):
            raw_obj = obj
            value = obj.get("value", None)
            md = obj.get("metadata") or {}
            ts = _parse_iso_ts(md.get("timestamp")) or now

            sc = md.get("status_code") or {}
            status_source = sc.get("source")
            status_code = sc.get("code")
            status_message = sc.get("message")
            silent_for_s = sc.get("silent_for_s")
            trigger = sc.get("trigger") or md.get("trigger")

            # value может быть строкой числа, числом, текстом, null
            vnum = _try_float(value)
            vtext = None
            if vnum is None and value is not None:
                # сохраняем как текст
                vtext = str(value)

            return ParsedMessage(
                topic=topic,
                ts=ts,
                trigger=trigger,
                status_source=status_source,
                status_code=int(status_code) if status_code is not None else None,
                status_message=str(status_message) if status_message is not None else None,
                silent_for_s=int(silent_for_s) if silent_for_s is not None else None,
                value_num=vnum,
                value_text=vtext,
                raw=raw_obj,
            )
    except Exception:
        pass

    # 2) Не JSON: пытаемся как число/текст
    try:
        s = payload_bytes.decode("utf-8", errors="replace").strip()
    except Exception:
        s = str(payload_bytes)

    vnum = _try_float(s)
    vtext = None if vnum is not None else s

    return ParsedMessage(
        topic=topic,
        ts=now,
        trigger=None,
        status_source=None,
        status_code=None,
        status_message=None,
        silent_for_s=None,
        value_num=vnum,
        value_text=vtext,
        raw=None,
    )
