"""MQTT adapter: the edge's EventPublisher and ConfigSource over Mosquitto.

- LWT: `DeviceStatus(offline)` retained on `status`; `online` is published on every connect.
- Persistent session (MQTT v5, `clean_start=False`) so QoS 1 messages survive short drops.
- Snapshot JPEG is published before its AlertEvent / StaffSuggestion so ingest can attach it.
- Retained `rules`, `profiles` and `config` are cached; getters are thread-safe.
- `camera()` prefers this device's camera from the retained `DeviceConfig` (matched by
  `camera_id`, else the first one) over the camera given at construction.
- `commands` (not retained) are queued; the pipeline drains them with `take_commands()` on
  its own thread, so the network thread never touches pipeline state.
"""

import logging
import threading
from collections import deque
from typing import Any

import paho.mqtt.client as mqtt
from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import Detections
from aivee_contracts.events import (
    AlertEvent,
    DeviceStatus,
    Metrics,
    StaffProfiles,
    StaffSuggestion,
)
from aivee_contracts.geometry import CameraConfig, DeviceConfig
from aivee_contracts.rules import Rule, RuleSet
from aivee_contracts.topics import Topics
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from pydantic import ValidationError

log = logging.getLogger(__name__)

SESSION_EXPIRY_S = 3600
MAX_PENDING_COMMANDS = 256


class MqttEdgeClient:
    """Implements `EventPublisher`, `ConfigSource` and `CommandSource` for one edge device."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        site: str,
        device: str,
        *,
        camera: CameraConfig | None = None,
        camera_id: str | None = None,
        version: str = "0.1.0",
        keepalive: int = 30,
    ) -> None:
        self.topics = Topics(site=site, device=device)
        self._host, self._port, self._keepalive = host, port, keepalive
        self._device, self._version = device, version
        self._lock = threading.Lock()
        self._camera = camera
        self._camera_id = camera_id or (camera.id if camera else None)
        self._config: DeviceConfig | None = None
        self._rules: RuleSet | None = None
        self._profiles: StaffProfiles | None = None
        self._commands: deque[EdgeCommand] = deque(maxlen=MAX_PENDING_COMMANDS)
        self.connected = threading.Event()

        self._client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"edge-{site}-{device}",
            protocol=mqtt.MQTTv5,
        )
        self._client.username_pw_set(user, password)
        self._client.will_set(self.topics.status, self._status("offline"), qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    # -- lifecycle -----------------------------------------------------------------

    def start(self, timeout: float | None = 10.0) -> None:
        """Connect and run the network loop in a background thread."""
        props = Properties(PacketTypes.CONNECT)  # type: ignore[no-untyped-call]
        props.SessionExpiryInterval = SESSION_EXPIRY_S
        self._client.connect_async(
            self._host,
            self._port,
            keepalive=self._keepalive,
            clean_start=False,
            properties=props,
        )
        self._client.loop_start()
        if timeout is not None and not self.connected.wait(timeout):
            raise TimeoutError(f"MQTT connect to {self._host}:{self._port} timed out")

    def stop(self) -> None:
        """Graceful stop: publish `offline` ourselves, then disconnect (no LWT)."""
        if self.connected.is_set():
            self._client.publish(
                self.topics.status, self._status("offline"), qos=1, retain=True
            ).wait_for_publish(5)
        self._client.disconnect()
        self._client.loop_stop()
        self.connected.clear()

    # -- EventPublisher ------------------------------------------------------------

    def publish_alert(self, event: AlertEvent, snapshot_jpeg: bytes | None) -> None:
        if snapshot_jpeg is not None:
            self._client.publish(self.topics.snapshot(event.event_id), snapshot_jpeg, qos=1)
            event = event.model_copy(update={"snapshot": True})
        self._client.publish(self.topics.events, event.model_dump_json(), qos=1)

    def publish_suggestion(self, suggestion: StaffSuggestion, snapshot_jpeg: bytes | None) -> None:
        if snapshot_jpeg is not None:
            topic = self.topics.snapshot(suggestion.suggestion_id)
            self._client.publish(topic, snapshot_jpeg, qos=1)
            suggestion = suggestion.model_copy(update={"snapshot": True})
        self._client.publish(self.topics.suggestions, suggestion.model_dump_json(), qos=1)

    def publish_detections(self, detections: Detections) -> None:
        self._client.publish(self.topics.detections, detections.model_dump_json(), qos=0)

    def publish_metrics(self, metrics: Metrics) -> None:
        self._client.publish(self.topics.metrics, metrics.model_dump_json(), qos=0)

    # -- ConfigSource --------------------------------------------------------------

    def rules(self) -> list[Rule]:
        with self._lock:
            return list(self._rules.rules) if self._rules else []

    def camera(self) -> CameraConfig:
        with self._lock:
            camera = self._configured_camera() or self._camera
        if camera is None:
            raise LookupError("no camera config set for this device")
        return camera

    def device_config(self) -> DeviceConfig | None:
        with self._lock:
            return self._config

    def _configured_camera(self) -> CameraConfig | None:
        if self._config is None or not self._config.cameras:
            return None
        cameras = self._config.cameras
        if self._camera_id is None:
            return cameras[0]
        return next((c for c in cameras if c.id == self._camera_id), None)

    def set_camera(self, camera: CameraConfig) -> None:
        with self._lock:
            self._camera = camera

    def profiles(self) -> StaffProfiles | None:
        with self._lock:
            return self._profiles

    # -- CommandSource -------------------------------------------------------------

    def take_commands(self) -> list[EdgeCommand]:
        with self._lock:
            out = list(self._commands)
            self._commands.clear()
        return out

    # -- callbacks -----------------------------------------------------------------

    def _status(self, state: str) -> str:
        with self._lock:
            camera = self._configured_camera() or self._camera
            cameras = [camera.id] if camera else []
        return DeviceStatus.model_validate(
            {"device": self._device, "state": state, "version": self._version, "cameras": cameras}
        ).model_dump_json()

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason: ReasonCode,
        _props: Properties | None,
    ) -> None:
        if reason.is_failure:
            log.error("MQTT connect refused: %s", reason)
            return
        client.subscribe(
            [
                (self.topics.rules, 1),
                (self.topics.profiles, 1),
                (self.topics.config, 1),
                (self.topics.commands, 1),
            ]
        )
        client.publish(self.topics.status, self._status("online"), qos=1, retain=True)
        self.connected.set()
        log.info("edge %s connected to MQTT", self._device)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            if msg.topic == self.topics.rules:
                ruleset = RuleSet.model_validate_json(msg.payload)
                with self._lock:
                    self._rules = ruleset
            elif msg.topic == self.topics.profiles:
                profiles = StaffProfiles.model_validate_json(msg.payload)
                with self._lock:
                    self._profiles = profiles
            elif msg.topic == self.topics.config:
                config = DeviceConfig.model_validate_json(msg.payload)
                with self._lock:
                    self._config = config
            elif msg.topic == self.topics.commands:
                command = EdgeCommand.model_validate_json(msg.payload)
                with self._lock:
                    self._commands.append(command)
                log.info("command received command_id=%s kind=%s", command.command_id, command.kind)
        except ValidationError:
            log.exception("ignoring invalid payload on %s", msg.topic)
