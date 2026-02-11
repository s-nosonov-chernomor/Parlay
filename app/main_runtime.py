# app/main_runtime.py
from __future__ import annotations

from typing import Optional

from app.services.command_service import CommandService

_command_service: Optional[CommandService] = None


def set_command_service(svc: CommandService) -> None:
    global _command_service
    _command_service = svc


def get_command_service() -> CommandService:
    if _command_service is None:
        raise RuntimeError("CommandService is not initialized yet")
    return _command_service
