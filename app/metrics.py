# app/metrics.py
from __future__ import annotations
from prometheus_client import Counter, Gauge

# сколько сообщений приняли из MQTT
mqtt_messages_total = Counter(
    "mqtt_messages_total",
    "Total MQTT messages received"
)

# сколько реально записали в БД
readings_processed_total = Counter(
    "readings_processed_total",
    "Readings written to database"
)

# сколько дропнули из-за переполнения очереди
ingest_dropped_total = Counter(
    "ingest_dropped_total",
    "Dropped ingest messages"
)

# текущий размер очереди
ingest_queue_size = Gauge(
    "ingest_queue_size",
    "Current ingest queue size"
)

# MQTT соединение
mqtt_connected = Gauge(
    "mqtt_connected",
    "MQTT connection status (1=connected)"
)

db_flush_errors_total = Counter(
    "db_flush_errors_total",
    "Database flush errors"
)

ingest_batch_size_last = Gauge(
    "ingest_batch_size_last",
    "Last batch size written to DB"
)

active_sse_connections = Gauge(
    "active_sse_connections",
    "Number of active SSE connections"
)