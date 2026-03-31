# app/main.py
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.settings import get_settings
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

from app.api.v1.routes_ui_par_dli import router as ui_par_dli_router
from app.services.par_dli_engine import ParDliEngine

from app.runtime import set_ingest

from starlette.middleware.sessions import SessionMiddleware
from app.api.v1.routes_auth import router as auth_router


# =========================
# Settings
# =========================
settings = get_settings()


# =========================
# Helpers (PyInstaller-safe path)
# =========================
def resource_path(rel: str) -> Path:
    # PyInstaller --onefile/--onedir: распаковывает/кладёт рядом, root = sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return (Path(sys._MEIPASS) / rel).resolve()
    # обычный запуск из исходников: .../Parlay/app/main.py -> root=.../Parlay
    return (Path(__file__).resolve().parents[1] / rel).resolve()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# =========================
# Runtime singletons
# =========================
logger = logging.getLogger("app")

limiter = PerTopicDebounce(min_interval_ms=150)

auto_engine = AutoEngine(
    tick_s=1.0,
    tz_default="Europe/Riga",
    max_commands_per_tick=5000,
)
priva_engine = PrivaEngine(tick_s=1.0, max_commands_per_tick=5000)

ingest = IngestService()
mqtt_client = MqttClient(on_message=lambda topic, payload: ingest.push(topic, payload))
command_service = CommandService(mqtt=mqtt_client)

par_dli_engine = ParDliEngine(
    tick_s=1.0,
    tz_default="Europe/Riga",
    max_commands_per_tick=5000,
)

# =========================
# Lifespan (startup/shutdown)
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    ingest.start()

    try:
        mqtt_client.start()
        logger.info("MQTT connected")
    except Exception:
        logger.exception("MQTT connect failed. Running WITHOUT MQTT.")

    auto_engine.start()
    priva_engine.start()
    par_dli_engine.start()

    set_command_service(command_service)
    set_ingest(ingest)
    set_limiter(limiter)

    logger.info("Service started")

    yield

    # SHUTDOWN
    par_dli_engine.stop()
    priva_engine.stop()
    auto_engine.stop()
    mqtt_client.stop()
    ingest.stop()

    logger.info("Service stopped")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key="change-me-super-secret-session-key",
    session_cookie="parlay_session",
    same_site="lax",
    https_only=False,   # для localhost; на проде под HTTPS поставить True
    max_age=60 * 60 * 12,
)

# =========================
# CORS (для dev фронта)
# =========================
cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

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


# =========================
# Health
# =========================
@app.get("/health")
def health():
    return {"ok": True, "env": settings.env}


# =========================
# API v1
# =========================
app.include_router(parameters_router, prefix="/v1")
app.include_router(readings_router, prefix="/v1")
app.include_router(commands_router, prefix="/v1")
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
# misc (без /v1)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(ui_par_dli_router, prefix="/v1")
app.include_router(auth_router, prefix="/v1")

# =========================
# Frontend (Vite dist) serving
# =========================
DIST_DIR = resource_path("frontend/dist")
ASSETS_DIR = DIST_DIR / "assets"

if DIST_DIR.exists():
    # 1) статика Vite
    if ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

    # 2) отдельные корневые файлы dist
    @app.get("/favicon.ico")
    def favicon():
        f = DIST_DIR / "favicon.ico"
        if f.exists():
            return FileResponse(str(f))
        return {"detail": "Not found"}

    @app.get("/vite.svg")
    def vite_svg():
        f = DIST_DIR / "vite.svg"
        if f.exists():
            return FileResponse(str(f))
        return {"detail": "Not found"}

    @app.get("/persay.ico")
    def persay_ico():
        f = DIST_DIR / "persay.ico"
        if f.exists():
            return FileResponse(str(f))
        return {"detail": "Not found"}

    # 3) корень SPA
    @app.get("/")
    def spa_index():
        return FileResponse(str(DIST_DIR / "index.html"))

    # 4) SPA fallback для react-router
    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("v1/") or full_path == "v1":
            return {"detail": "Not found"}
        return FileResponse(str(DIST_DIR / "index.html"))

# =========================================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,  # <-- ВАЖНО: объект, не "app.main:app"
        host=settings.http_host,
        port=settings.http_port,
        log_level="info",
    )
