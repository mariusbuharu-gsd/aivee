"""One-off jobs the API asks the edge for (`EdgeRequest` on `commands`), answered with exactly
one `EdgeReply` on `replies`:

- `discover_cameras`: the IP cameras on the device's network (`adapters.discovery`).
- `test_camera`: one face-blurred still of a camera URL, or why there is none
  (`adapters.camera_still`).

The MQTT network thread only queues a request (`submit`); a small pool runs the jobs, so a
discovery (about 5 s) never stalls the cameras' rules and zones. Camera URLs carry passwords:
they are never logged.
"""

import base64
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from aivee_contracts.commands import DiscoveredCamera, EdgeReply, EdgeRequest

from aivee_edge.adapters.camera_still import CameraTestError, Still
from aivee_edge.redact import redact_text

log = logging.getLogger("aivee_edge.jobs")

WORKERS = 2


class EdgeJobs:
    def __init__(
        self,
        device: str,
        publish: Callable[[EdgeReply], None],
        *,
        discover: Callable[[], list[DiscoveredCamera]],
        test: Callable[[str], Still],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        workers: int = WORKERS,
    ) -> None:
        self._device = device
        self._publish = publish
        self._discover = discover
        self._test = test
        self._clock = clock
        self._pool = ThreadPoolExecutor(workers, thread_name_prefix="edge job")

    def submit(self, request: EdgeRequest) -> None:
        """Queue a request; returns at once (it is called on the MQTT network thread)."""
        self._pool.submit(self._run, request)

    def close(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)

    def _run(self, request: EdgeRequest) -> None:
        reply = self.handle(request)
        try:
            self._publish(reply)
        except Exception as e:
            log.error("reply_failed request_id=%s: %s", request.request_id, e)

    def _reply(self, request: EdgeRequest, **fields: object) -> EdgeReply:
        return EdgeReply.model_validate(
            {
                "request_id": request.request_id,
                "kind": request.kind,
                "device": self._device,
                "at": self._clock(),
                **fields,
            }
        )

    def handle(self, request: EdgeRequest) -> EdgeReply:
        """Run one request and build its reply (never raises)."""
        started = time.monotonic()
        try:
            if request.kind == "discover_cameras":
                cameras = self._discover()
                log.info(
                    "discovery request_id=%s found=%d seconds=%.1f",
                    request.request_id,
                    len(cameras),
                    time.monotonic() - started,
                )
                return self._reply(request, ok=True, cameras=cameras)
            still = self._test(request.source or "")
        except CameraTestError as e:
            log.info(
                "%s request_id=%s error=%s seconds=%.1f",
                request.kind,
                request.request_id,
                e.code,
                time.monotonic() - started,
            )
            return self._reply(request, ok=False, error=e.code)
        except Exception as e:
            log.error(
                "job_failed request_id=%s kind=%s: %s",
                request.request_id,
                request.kind,
                redact_text(repr(e)),
            )
            return self._reply(request, ok=False, error="failed")
        log.info(
            "camera_test request_id=%s ok size=%dx%d seconds=%.1f",
            request.request_id,
            still.width,
            still.height,
            time.monotonic() - started,
        )
        return self._reply(
            request,
            ok=True,
            jpeg_b64=base64.b64encode(still.jpeg).decode("ascii"),
            width=still.width,
            height=still.height,
            frame_at=still.at,
        )
