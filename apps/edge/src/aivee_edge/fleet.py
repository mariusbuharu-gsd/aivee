"""The edge box's cameras follow the dashboard: `CameraFleet.reconcile()` compares the cameras
the device runs with the live cameras of its retained `DeviceConfig` (`domain.fleet`) and
starts, stops or restarts camera workers on the running `Supervisor`, leaving the others
alone. It runs on the supervisor's thread, once per tick.

A camera whose worker cannot be built (missing model files, a bad source) is logged once and
retried only when its source changes. Passwords never reach the log.
"""

import logging
from collections.abc import Callable
from typing import Protocol

from aivee_contracts.geometry import CameraConfig, DeviceConfig

from aivee_edge.domain.fleet import is_live_source, plan_fleet, wanted_cameras
from aivee_edge.redact import redact_text, redact_url
from aivee_edge.supervisor import CameraRun

log = logging.getLogger("aivee_edge.fleet")


class FleetClient(Protocol):
    def device_config(self) -> DeviceConfig | None: ...

    def drop_camera(self, camera_id: str) -> None: ...


class FleetSupervisor(Protocol):
    def add(self, cam: CameraRun) -> None: ...

    def remove(self, camera_id: str) -> None: ...


class FleetHealth(Protocol):
    def add(self, camera_id: str, source: object) -> None: ...

    def remove(self, camera_id: str) -> None: ...


class CameraFleet:
    def __init__(
        self,
        supervisor: FleetSupervisor,
        client: FleetClient,
        health: FleetHealth,
        build: Callable[[CameraConfig], CameraRun],
    ) -> None:
        """`build` makes one camera's worker and registers it on the MQTT client."""
        self._supervisor = supervisor
        self._client = client
        self._health = health
        self._build = build
        self._running: dict[str, str] = {}
        self._failed: dict[str, str] = {}
        self._skipped: dict[str, str] = {}

    def running(self) -> dict[str, str]:
        """camera id → source of every camera this box runs now."""
        return dict(self._running)

    def reconcile(self) -> None:
        config = self._client.device_config()
        if config is None:
            return  # the retained config has not arrived yet
        cameras = {c.id: c for c in config.cameras}
        self._log_skipped(config.cameras)
        wanted = wanted_cameras((c.id, c.source) for c in config.cameras)
        self._failed = {cid: src for cid, src in self._failed.items() if wanted.get(cid) == src}
        changes = plan_fleet(self._running, wanted, self._failed)
        for camera_id in changes.stop:
            self._stop(camera_id, "changed" if camera_id in wanted else "removed")
        for camera_id in changes.start:
            self._start(cameras[camera_id])

    def stop_all(self) -> None:
        for camera_id in sorted(self._running):
            self._stop(camera_id, "stopping")

    def _start(self, camera: CameraConfig) -> None:
        try:
            run = self._build(camera)
        except Exception as e:
            self._failed[camera.id] = camera.source
            self._client.drop_camera(camera.id)
            log.error(
                "camera_start_failed camera=%s source=%s: %s",
                camera.id,
                redact_url(camera.source),
                redact_text(str(e)),
            )
            return
        self._supervisor.add(run)
        self._health.add(camera.id, run.source)
        self._running[camera.id] = camera.source
        log.info("camera_started camera=%s source=%s", camera.id, redact_url(camera.source))

    def _stop(self, camera_id: str, why: str) -> None:
        self._supervisor.remove(camera_id)
        self._health.remove(camera_id)
        self._client.drop_camera(camera_id)
        self._running.pop(camera_id, None)
        log.info("camera_stopped camera=%s reason=%s", camera_id, why)

    def _log_skipped(self, cameras: list[CameraConfig]) -> None:
        """Say once per camera and source why a configured camera does not run here."""
        skipped = {c.id: c.source for c in cameras if not is_live_source(c.source)}
        for camera_id, source in skipped.items():
            if self._skipped.get(camera_id) != source:
                log.info(
                    "camera_skipped camera=%s source=%s: not an RTSP/HTTP stream this box reads",
                    camera_id,
                    redact_url(source),
                )
        self._skipped = skipped
