# app/metrics_auto.py
from __future__ import annotations

from prometheus_client import Counter, Gauge

auto_ticks_total = Counter("auto_ticks_total", "AUTO engine ticks")
auto_elements_total = Gauge("auto_elements_total", "AUTO elements processed in last tick")
auto_commands_sent_total = Counter("auto_commands_sent_total", "AUTO commands published")
auto_commands_skipped_total = Counter("auto_commands_skipped_total", "AUTO commands skipped (no change / missing data)")
auto_errors_total = Counter("auto_errors_total", "AUTO engine errors")
