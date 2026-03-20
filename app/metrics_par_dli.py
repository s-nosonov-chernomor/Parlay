# app/metrics_par_dli.py

from prometheus_client import Counter, Gauge

par_dli_ticks_total = Counter(
    "par_dli_ticks_total",
    "Total PAR_DLI engine ticks",
)

par_dli_elements_total = Gauge(
    "par_dli_elements_total",
    "Current number of UI elements in PAR_DLI mode",
)

par_dli_commands_sent_total = Counter(
    "par_dli_commands_sent_total",
    "Total PAR_DLI commands sent",
)

par_dli_commands_skipped_total = Counter(
    "par_dli_commands_skipped_total",
    "Total PAR_DLI commands skipped",
)

par_dli_errors_total = Counter(
    "par_dli_errors_total",
    "Total PAR_DLI engine errors",
)