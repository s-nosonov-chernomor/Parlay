# app/runtime_limiter.py
from __future__ import annotations

from typing import Optional
from app.services.rate_limiter import PerTopicDebounce

_limiter: Optional[PerTopicDebounce] = None


def set_limiter(l: PerTopicDebounce) -> None:
    global _limiter
    _limiter = l


def get_limiter() -> PerTopicDebounce:
    if _limiter is None:
        raise RuntimeError("Limiter is not initialized")
    return _limiter
