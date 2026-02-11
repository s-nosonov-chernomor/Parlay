# app/runtime.py
from __future__ import annotations

from typing import Optional

from app.services.ingest_service import IngestService

_ingest: Optional[IngestService] = None
_mqtt_connected: bool = False


def set_ingest(svc: IngestService) -> None:
    global _ingest
    _ingest = svc


def get_ingest() -> IngestService:
    if _ingest is None:
        raise RuntimeError("IngestService is not initialized")
    return _ingest


def set_mqtt_connected(v: bool) -> None:
    global _mqtt_connected
    _mqtt_connected = v


def get_mqtt_connected() -> bool:
    return _mqtt_connected
