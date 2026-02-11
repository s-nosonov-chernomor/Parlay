# app/api/auth.py
from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.settings import get_settings
settings = get_settings()


def require_token(x_api_token: str | None = Header(default=None)) -> None:
    """
    Простейшая защита: клиент должен прислать заголовок X-API-Token.
    Если API_TOKEN не задан — защита отключена (удобно для dev).
    """
    if not settings.api_token:
        return
    if x_api_token != settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
        )
