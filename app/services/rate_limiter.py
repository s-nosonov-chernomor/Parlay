# app/services/rate_limiter.py
from __future__ import annotations

import time
import threading
from collections import defaultdict


class PerTopicDebounce:
    """
    Антидребезг: не позволяет отправлять команды на один и тот же topic
    чаще, чем раз в min_interval_ms.

    ВАЖНО: это НЕ тормозит залпы по зоне (потому что topics разные).
    """
    def __init__(self, min_interval_ms: int = 150):
        self.min_interval_ms = min_interval_ms
        self._lock = threading.Lock()
        self._last_ts = defaultdict(lambda: 0.0)

    def allow(self, topic: str) -> bool:
        now = time.time()
        with self._lock:
            last = self._last_ts[topic]
            if (now - last) * 1000.0 < self.min_interval_ms:
                return False
            self._last_ts[topic] = now
            return True
