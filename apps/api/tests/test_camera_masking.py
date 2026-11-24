"""Camera passwords never leave the API: sources are masked in every response, and an edit
that sends the masked value back keeps the stored password."""

from datetime import UTC, datetime

import pytest
from aivee_api.audit.models import AuditRow
from aivee_api.audit.router import entry_out
from aivee_api.cameras.masking import (
    MASK,
    MaskedWithoutPassword,
    is_masked,
    mask_source,
    restore_masked,
    url_host,
)


@pytest.mark.parametrize(
    ("source", "shown"),
    [
        (
            "rtsp://admin:s3cr3t@192.168.1.21:554/stream2",
            "rtsp://admin:***@192.168.1.21:554/stream2",
        ),
        ("rtsp://admin:p%40ss@cam.local/stream1", "rtsp://admin:***@cam.local/stream1"),
        ("rtsp://admin@192.168.1.21/stream2", "rtsp://admin@192.168.1.21/stream2"),
        ("rtsp://192.168.1.21:554/stream2", "rtsp://192.168.1.21:554/stream2"),
        (
            "rtsp://192.168.1.30/cam/realmonitor?channel=1&subtype=1",
            "rtsp://192.168.1.30/cam/realmonitor?channel=1&subtype=1",
        ),
        (
            "http://192.168.1.40/video.cgi?user=admin&password=x1&res=1",
            "http://192.168.1.40/video.cgi?user=admin&password=***&res=1",
        ),
        ("0", "0"),
        ("mqtt-frames://cam-01", "mqtt-frames://cam-01"),
        ("recordings/sala.mp4", "recordings/sala.mp4"),
    ],
)
def test_mask_hides_only_the_password(source: str, shown: str) -> None:
    assert mask_source(source) == shown


def test_is_masked() -> None:
    assert is_masked("rtsp://admin:***@192.168.1.21/stream2")
    assert is_masked("http://h/v.cgi?password=***")
    assert not is_masked("rtsp://admin:s3cr3t@192.168.1.21/stream2")
    assert not is_masked("0")


def test_restore_keeps_the_stored_password_with_a_new_host_or_user() -> None:
    stored = "rtsp://admin:p%40ss@192.168.1.21:554/stream2"
    assert restore_masked(mask_source(stored), stored) == stored
    assert (
        restore_masked("rtsp://viewer:***@192.168.1.99:554/stream1", stored)
        == "rtsp://viewer:p%40ss@192.168.1.99:554/stream1"
    )
    stored_q = "http://h/v.cgi?user=a&password=x1"
    assert restore_masked("http://h2/v.cgi?user=a&password=***", stored_q) == (
        "http://h2/v.cgi?user=a&password=x1"
    )


def test_restore_leaves_a_new_password_alone() -> None:
    stored = "rtsp://admin:old@192.168.1.21/stream2"
    assert restore_masked("rtsp://admin:new@192.168.1.21/stream2", stored) == (
        "rtsp://admin:new@192.168.1.21/stream2"
    )


def test_restore_without_a_stored_password_is_refused() -> None:
    with pytest.raises(MaskedWithoutPassword):
        restore_masked("rtsp://admin:***@192.168.1.21/stream2", "rtsp://192.168.1.21/stream2")
    with pytest.raises(MaskedWithoutPassword):
        restore_masked("http://h/v.cgi?password=***", "http://h/v.cgi")


def test_url_host() -> None:
    assert url_host("rtsp://admin:x@192.168.1.21:554/stream2") == "192.168.1.21"
    assert url_host("rtsp://Cam.Local/stream2") == "cam.local"
    assert url_host("0") is None
    assert url_host("rtsp://") is None


def test_old_audit_entries_are_masked_on_read() -> None:
    row = AuditRow(
        id=7,
        at=datetime(2026, 11, 20, tzinfo=UTC),
        location_id="test",
        actor_kind="user",
        actor_id="u1",
        actor_name="Olga",
        kind="camera.updated",
        target_type="camera",
        target_id="cam-01",
        target_label="Sala",
        summary_ro="Olga a modificat camera Sala",
        before={"id": "cam-01", "source": "rtsp://admin:old@192.168.1.21/stream2"},
        after={"id": "cam-01", "source": "rtsp://admin:new@192.168.1.21/stream2"},
    )
    entry = entry_out(row)
    assert entry.before["source"] == f"rtsp://admin:{MASK}@192.168.1.21/stream2"
    assert entry.after["source"] == f"rtsp://admin:{MASK}@192.168.1.21/stream2"
    dumped = str(entry.model_dump())
    assert ":old@" not in dumped and ":new@" not in dumped
