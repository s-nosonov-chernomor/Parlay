# app/metrics_priva.py
from __future__ import annotations

from prometheus_client import Counter, Gauge

priva_ticks_total = Counter("priva_ticks_total", "PRIVA engine ticks")
priva_elements_total = Gauge("priva_elements_total", "PRIVA elements processed in last tick")
priva_commands_sent_total = Counter("priva_commands_sent_total", "PRIVA commands published")
priva_commands_skipped_total = Counter("priva_commands_skipped_total", "PRIVA commands skipped (no change / missing data)")
priva_errors_total = Counter("priva_errors_total", "PRIVA engine errors")
