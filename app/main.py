# app/main.py
from __future__ import annotations

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.settings import get_settings
settings = get_settings()

from app.mqtt.client import MqttClient
from app.services.ingest_service import IngestService
from app.services.command_service import CommandService
from app.main_runtime import set_command_service

from app.services.rate_limiter import PerTopicDebounce
from app.runtime_limiter import set_limiter

from app.api.v1.routes_parameters import router as parameters_router
from app.api.v1.routes_readings import router as readings_router
from app.api.v1.routes_commands import router as commands_router
from app.api.v1.routes_stream import router as stream_router

from app.api.health import router as health_router
from app.api.metrics import router as metrics_router

from app.api.v1.routes_ui import router as ui_router
from app.api.v1.routes_ui_mode import router as ui_mode_router
from app.api.v1.routes_schedules import router as schedules_router

from app.services.auto_engine import AutoEngine
from app.services.priva_engine import PrivaEngine
from app.api.v1.routes_ui_set import router as ui_set_router
from app.api.v1.routes_ui_snapshot import router as ui_snapshot_router
from app.api.v1.routes_ui_stream import router as ui_stream_router
from app.api.v1.routes_power import router as power_router
from app.api.v1.routes_cabinets import router as cabinets_router
from app.api.v1.routes_health_grid import router as health_grid_router
from app.api.v1.routes_health_detail import router as health_detail_router
from app.api.v1.routes_query import router as query_router

from app.runtime import set_ingest

app = FastAPI(title=settings.app_name)

# =========================
# CORS (для фронта Vite/React)
# =========================
# В dev удобно разрешить localhost:5173 и локальные IP.
# В прод лучше сузить allow_origins до конкретных доменов.
cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Если фронт открываешь с другого ПК по LAN (например http://192.168.x.x:5173),
# то удобнее разрешить все origins в dev. Ниже безопасный компромисс:
# - если env=dev -> allow_origin_regex на локальную сеть
# - иначе только фиксированный список
if getattr(settings, "env", "").lower() in ("dev", "development", "local"):
    app.add_middleware(
        CORSMiddleware,

        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?$",
        allow_credentials=True,

        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )


logger = logging.getLogger("app")

limiter = PerTopicDebounce(min_interval_ms=150)

auto_engine = AutoEngine(tick_s=1.0, tz_default="Europe/Riga", max_commands_per_tick=5000)
priva_engine = PrivaEngine(tick_s=1.0, max_commands_per_tick=5000)

ingest = IngestService()
mqtt_client = MqttClient(on_message=lambda topic, payload: ingest.push(topic, payload))
command_service = CommandService(mqtt=mqtt_client)

@app.on_event("startup")
def _startup():
    ingest.start()

    try:
        mqtt_client.start()
        logger.info("MQTT connected")
    except Exception:
        logger.exception("MQTT connect failed. Running WITHOUT MQTT.")

    auto_engine.start()
    priva_engine.start()
    set_command_service(command_service)
    set_ingest(ingest)
    set_limiter(limiter)
    logger.info("Service started")

@app.on_event("shutdown")
def _shutdown():
    priva_engine.stop()
    auto_engine.stop()
    mqtt_client.stop()
    ingest.stop()
    logger.info("Service stopped")

@app.get("/health")
def health():
    return {"ok": True, "env": settings.env}


# API v1
app.include_router(parameters_router, prefix="/v1")
app.include_router(readings_router, prefix="/v1")
app.include_router(commands_router, prefix="/v1")
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(stream_router, prefix="/v1")
app.include_router(ui_router, prefix="/v1")
app.include_router(ui_mode_router, prefix="/v1")
app.include_router(schedules_router, prefix="/v1")
app.include_router(ui_set_router, prefix="/v1")
app.include_router(ui_snapshot_router, prefix="/v1")
app.include_router(ui_stream_router, prefix="/v1")
app.include_router(power_router, prefix="/v1")
app.include_router(cabinets_router, prefix="/v1")
app.include_router(health_grid_router, prefix="/v1")
app.include_router(health_detail_router, prefix="/v1")
app.include_router(query_router, prefix="/v1")
