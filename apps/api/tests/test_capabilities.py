"""`GET /api/capabilities` without a database: the flags follow the server's wiring."""

from pathlib import Path
from typing import Any

from aivee_api.capabilities import capabilities
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.settings import ApiSettings


def _settings(tmp_path: Path, **kw: Any) -> ApiSettings:
    return ApiSettings(
        site="test", device="edge-01", snapshot_dir=tmp_path / "s", mqtt_enabled=False, **kw
    )


def test_a_plain_server_has_neither(tmp_path: Path, services_factory: Any, translator: Any) -> None:
    svc = services_factory(_settings(tmp_path), None, RecordingPublisher(), translator)
    assert capabilities(svc).model_dump() == {"videos": False, "enrol": False}


def test_videos_need_the_queue_and_the_runner_login(
    tmp_path: Path, services_factory: Any, translator: Any, fake_enroller: Any
) -> None:
    s = _settings(tmp_path, mqtt_upload_user="upload-01", mqtt_upload_password="pw")
    svc = services_factory(s, None, RecordingPublisher(), translator, fake_enroller)
    assert capabilities(svc).model_dump() == {"videos": False, "enrol": True}
    svc.videos = object()
    assert capabilities(svc).videos is True
    s.mqtt_upload_password = ""
    assert capabilities(svc).videos is False
