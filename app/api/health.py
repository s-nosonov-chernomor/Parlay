# app/api/health.py
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import engine
from app.runtime import get_ingest, get_mqtt_connected
from app.sse.hub import hub

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz():
    db_ok = True
    db_err = None
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as e:
        db_ok = False
        db_err = str(e)

    mqtt_ok = get_mqtt_connected()

    qsize = None
    dropped = None
    processed = None
    try:
        ingest = get_ingest()
        qsize = ingest.queue.qsize()
        dropped = ingest._dropped
        processed = ingest._processed
    except Exception:
        pass

    return {
        "status": "ok" if (db_ok and mqtt_ok) else "degraded",
        "db": db_ok,
        "db_error": db_err,
        "mqtt_connected": mqtt_ok,
        "ingest_queue_size": qsize,
        "ingest_dropped": dropped,
        "ingest_processed": processed,
        "active_sse_connections": hub.active_connections(),

    }
