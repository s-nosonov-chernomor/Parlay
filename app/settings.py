# app/settings.py
from pathlib import Path
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

def runtime_root() -> Path:
    # когда собрали PyInstaller
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent  # папка рядом с exe
    # дев-режим
    return Path(__file__).resolve().parents[1]       # .../Parlay

ENV_PATH = runtime_root() / ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="mqtt-bridge", alias="APP_NAME")
    env: str = Field(default="dev", alias="ENV")

    http_host: str = Field(default="0.0.0.0", alias="HTTP_HOST")
    http_port: int = Field(default=8000, alias="HTTP_PORT")

    db_url: str = Field(alias="DB_URL")

    mqtt_host: str = Field(alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, alias="MQTT_PORT")
    mqtt_username: str | None = Field(default=None, alias="MQTT_USERNAME")
    mqtt_password: str | None = Field(default=None, alias="MQTT_PASSWORD")
    mqtt_client_id: str = Field(default="mqtt-bridge", alias="MQTT_CLIENT_ID")
    mqtt_subscribe: str = Field(default="#", alias="MQTT_SUBSCRIBE")
    mqtt_qos: int = Field(default=1, alias="MQTT_QOS")
    mqtt_keepalive: int = Field(default=60, alias="MQTT_KEEPALIVE")

    ingest_queue_max: int = Field(default=50000, alias="INGEST_QUEUE_MAX")
    db_batch_size: int = Field(default=500, alias="DB_BATCH_SIZE")
    db_flush_interval_ms: int = Field(default=250, alias="DB_FLUSH_INTERVAL_MS")
    param_cache_size: int = Field(default=200000, alias="PARAM_CACHE_SIZE")

    store_raw: bool = Field(default=True, alias="STORE_RAW")

    api_token: str | None = Field(default=None, alias="API_TOKEN")

    # === HEALTH / DIAGNOSTICS ===
    health_stale_s: int = Field(default=120, alias="HEALTH_STALE_S")
    health_silent_warn_s: int = Field(default=30, alias="HEALTH_SILENT_WARN_S")
    health_silent_crit_s: int = Field(default=120, alias="HEALTH_SILENT_CRIT_S")
    health_include_manual_topic: bool = Field(default=True, alias="HEALTH_INCLUDE_MANUAL_TOPIC")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings