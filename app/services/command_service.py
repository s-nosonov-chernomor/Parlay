# app/services/command_service.py

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import CommandLog
from app.mqtt.client import MqttClient


@dataclass(slots=True)
class CommandRequest:
    topic: str
    value: object  # int/float/str/bool/None
    as_json: bool = True
    requested_by: str | None = None
    correlation_id: str | None = None


class CommandService:
    def __init__(self, mqtt: MqttClient):
        self.mqtt = mqtt

    def send(self, session: Session, cmd: CommandRequest) -> int:
        topic_on = cmd.topic.rstrip("/") + "/on"

        if cmd.as_json:
            payload_str = json.dumps({"value": cmd.value}, ensure_ascii=False)
        else:
            payload_str = "" if cmd.value is None else str(cmd.value)

        self.mqtt.publish(topic_on, payload_str, qos=1, retain=False)

        rec = CommandLog(
            topic=cmd.topic,
            topic_on=topic_on,
            payload=payload_str,
            requested_by=cmd.requested_by,
            correlation_id=cmd.correlation_id,
        )
        session.add(rec)
        session.flush()  # получить id
        return int(rec.id)

    def make_request(
        self,
        topic: str,
        value: object | None,
        as_json: bool = True,
        requested_by: str | None = None,
        correlation_id: str | None = None,
    ) -> CommandRequest:
        return CommandRequest(
            topic=topic,
            value=value,
            as_json=as_json,
            requested_by=requested_by,
            correlation_id=correlation_id,
        )