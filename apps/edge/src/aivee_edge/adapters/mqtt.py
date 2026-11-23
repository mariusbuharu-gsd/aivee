"""MQTT adapter: the edge's EventPublisher and ConfigSource over Mosquitto.

- LWT: `DeviceStatus(offline)` retained on `status`; `online` is published on every connect.
- Persistent session (MQTT v5, `clean_start=False`) so QoS 1 messages survive short drops.
- Snapshot JPEG is published before its AlertEvent / StaffSuggestion so ingest can attach it.
- Retained `rules`, `profiles` and `config` are cached; getters are thread-safe.
- `camera()` prefers this device's camera from the retained `DeviceConfig` (matched by
  `camera_id`, else the first one) over the camera given at construction.
- `commands` (not retained) are queued; the pipeline drains them with `take_commands()` on
  its own thread, so the network thread never touches pipeline state.
- Several cameras, one device (one MQTT connection, one client id): `for_camera()` gives each
  camera's pipeline a `CameraClient` view. Its `camera()` is that camera, its commands are the
  ones naming that camera, and its metrics are combined into one `Metrics` per device
  (`DeviceMetrics`). `DeviceStatus.cameras` lists every camera.
- Transport: plain TCP by default; `transport="websockets"` (+ `ws_path`) and `tls=True` let a
  remote edge reach the broker as `wss://host:443/path` through an HTTPS reverse proxy.
"""

import logging
import ssl
import threading
import time
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

from aivee_edge.metrics import DeviceMetrics

log = logging.getLogger(__name__)

SESSION_EXPIRY_S = 3600
MAX_PENDING_COMMANDS = 256
TRANSPORTS = ("tcp", "websockets")


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
        transport: str = "tcp",
        tls: bool = False,
        ws_path: str = "/mqtt",
        metrics_interval_s: float = 5.0,
    ) -> None:
        if transport not in TRANSPORTS:
            raise ValueError(f"MQTT transport must be one of {TRANSPORTS}, not {transport!r}")
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
        self._views: dict[str, CameraClient] = {}
        self._metrics_interval_s = metrics_interval_s
        self._device_metrics: DeviceMetrics | None = None
        self.connected = threading.Event()

        self._client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"edge-{site}-{device}",
            protocol=mqtt.MQTTv5,
            transport="websockets" if transport == "websockets" else "tcp",
        )
        if transport == "websockets":
            self._client.ws_set_options(path=ws_path)
        if tls:
            # System CA bundle, hostname checked: the server presents a public certificate.
            self._client.tls_set_context(ssl.create_default_context())
        self._client.username_pw_set(user, password)
        self._set_will()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _set_will(self) -> None:
        self._client.will_set(self.topics.status, self._status("offline"), qos=1, retain=True)

    def for_camera(self, camera: CameraConfig) -> "CameraClient":
        """Register one camera of this device and return its pipeline's view. Call before
        `start()`, so the status and the last will list every camera."""
        with self._lock:
            if camera.id in self._views:
                raise ValueError(f"camera {camera.id!r} is already registered")
            view = CameraClient(self, camera)
            self._views[camera.id] = view
            self._device_metrics = DeviceMetrics(
                self._device, list(self._views), self._metrics_interval_s
            )
        self._set_will()
        return view

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

    def publish_alert(
        self, event: AlertEvent, snapshot_jpeg: bytes | None, before_jpeg: bytes | None = None
    ) -> None:
        if snapshot_jpeg is not None:
            self._client.publish(self.topics.snapshot(event.event_id), snapshot_jpeg, qos=1)
            event = event.model_copy(update={"snapshot": True})
        if before_jpeg is not None and event.object_change is not None:
            self._client.publish(self.topics.snapshot_before(event.event_id), before_jpeg, qos=1)
            change = event.object_change.model_copy(update={"before_snapshot": True})
            event = event.model_copy(update={"object_change": change})
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

    def publish_camera_metrics(self, camera_id: str, metrics: Metrics) -> None:
        """One camera's sample; the device's combined Metrics goes out when it is due."""
        with self._lock:
            combined = (
                self._device_metrics.add(camera_id, metrics) if self._device_metrics else None
            )
        if combined is not None:
            self.publish_metrics(combined)

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

    def configured_camera(self, camera_id: str) -> CameraConfig | None:
        """`camera_id` from the retained `DeviceConfig`, None until it lists it."""
        with self._lock:
            if self._config is None:
                return None
            return next((c for c in self._config.cameras if c.id == camera_id), None)

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

    def wait_for_state(self, timeout: float) -> bool:
        """Wait until the retained `config` names this device's camera and a `rules` set
        arrived. An offline clip run uses it: it must not analyse frames without its zones
        and rules, and a clip has no "later" to pick them up in."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                ready = self._rules is not None and (
                    self._config is not None
                    and any(c.id == self._camera_id for c in self._config.cameras)
                )
            if ready or time.monotonic() >= deadline:
                return ready
            time.sleep(0.05)

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
            if self._views:
                cameras = list(self._views)
            else:
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
                self._route(command)
        except ValidationError:
            log.exception("ignoring invalid payload on %s", msg.topic)

    def _route(self, command: EdgeCommand) -> None:
        """Queue a command for the pipeline of its camera (or the single pipeline)."""
        with self._lock:
            view = self._views.get(command.camera_id)
            if view is not None:
                view._commands.append(command)
            elif not self._views:
                self._commands.append(command)
        if self._views and view is None:
            log.info(
                "command_ignored command_id=%s kind=%s camera=%s: not a camera of this device",
                command.command_id,
                command.kind,
                command.camera_id,
            )
            return
        log.info(
            "command received command_id=%s kind=%s camera=%s",
            command.command_id,
            command.kind,
            command.camera_id,
        )


class CameraClient:
    """One camera's view of the shared `MqttEdgeClient`: the `EventPublisher`,
    `ConfigSource` and `CommandSource` of that camera's pipeline."""

    def __init__(self, client: MqttEdgeClient, camera: CameraConfig) -> None:
        self._client = client
        self._fallback = camera
        self._commands: deque[EdgeCommand] = deque(maxlen=MAX_PENDING_COMMANDS)

    @property
    def camera_id(self) -> str:
        return self._fallback.id

    # EventPublisher
    def publish_alert(
        self, event: AlertEvent, snapshot_jpeg: bytes | None, before_jpeg: bytes | None = None
    ) -> None:
        self._client.publish_alert(event, snapshot_jpeg, before_jpeg)

    def publish_suggestion(self, suggestion: StaffSuggestion, snapshot_jpeg: bytes | None) -> None:
        self._client.publish_suggestion(suggestion, snapshot_jpeg)

    def publish_detections(self, detections: Detections) -> None:
        self._client.publish_detections(detections)

    def publish_metrics(self, metrics: Metrics) -> None:
        self._client.publish_camera_metrics(self.camera_id, metrics)

    # ConfigSource
    def rules(self) -> list[Rule]:
        return self._client.rules()

    def camera(self) -> CameraConfig:
        """This camera from the retained config (zones), else the one given at start."""
        return self._client.configured_camera(self.camera_id) or self._fallback

    def profiles(self) -> StaffProfiles | None:
        return self._client.profiles()

    # CommandSource
    def take_commands(self) -> list[EdgeCommand]:
        with self._client._lock:
            out = list(self._commands)
            self._commands.clear()
        return out
