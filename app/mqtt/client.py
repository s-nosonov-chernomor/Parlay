# app/mqtt/client.py

from __future__ import annotations

import logging
import threading
from typing import Callable

import paho.mqtt.client as mqtt

from app.settings import get_settings
settings = get_settings()

from app.metrics import mqtt_connected
from app.runtime import set_mqtt_connected

logger = logging.getLogger("mqtt")


class MqttClient:
    def __init__(self, on_message: Callable[[str, bytes], None]):
        self._on_message = on_message
        self._client = mqtt.Client(client_id=settings.mqtt_client_id, userdata=None, protocol=mqtt.MQTTv311)
        self._client.enable_logger(logger)

        if settings.mqtt_username:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password or "")

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_msg
        self._client.on_disconnect = self._on_disconnect

        self._thread: threading.Thread | None = None

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc != 0:
            logger.error("MQTT connect failed rc=%s", rc)
            return
        logger.info("MQTT connected. Subscribing to '%s' qos=%s", settings.mqtt_subscribe, settings.mqtt_qos)
        client.subscribe(settings.mqtt_subscribe, qos=settings.mqtt_qos)
        mqtt_connected.set(1)
        set_mqtt_connected(True)

    def _on_disconnect(self, client, userdata, rc, properties=None):
        logger.warning("MQTT disconnected rc=%s", rc)
        mqtt_connected.set(0)
        set_mqtt_connected(False)

    def _on_msg(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload or b""
            self._on_message(topic, payload)
        except Exception:
            logger.exception("Error handling MQTT message")

    def start(self):
        logger.info("MQTT connecting %s:%s ...", settings.mqtt_host, settings.mqtt_port)
        self._client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=settings.mqtt_keepalive)
        self._client.loop_start()

    def stop(self):
        try:
            self._client.loop_stop()
        finally:
            try:
                self._client.disconnect()
            except Exception:
                pass

    def publish(self, topic: str, payload: str | bytes, qos: int = 1, retain: bool = False):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self._client.publish(topic, payload=payload, qos=qos, retain=retain)
