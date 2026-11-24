import pytest
from aivee_edge.redact import redact_url


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        (
            "rtsp://admin:s3cr3t@192.168.1.20:554/stream2",
            "rtsp://admin:***@192.168.1.20:554/stream2",
        ),
        ("rtsp://tok3n@cam.local/live", "rtsp://***@cam.local/live"),
        ("rtsp://a:p%40ss@h/x?y=1", "rtsp://a:***@h/x?y=1"),
        (
            "http://192.168.1.30/video.cgi?user=admin&password=hunter2&ch=1",
            "http://192.168.1.30/video.cgi?user=admin&password=***&ch=1",
        ),
        ("http://h/v?token=abc", "http://h/v?token=***"),
        ("rtsp://mediamtx:8554/cam-01", "rtsp://mediamtx:8554/cam-01"),
        ("mqtt-frames://cam-coleg-1", "mqtt-frames://cam-coleg-1"),
        ("0", "0"),
        ("recordings/sala-1.mp4", "recordings/sala-1.mp4"),
        ("", ""),
    ],
)
def test_redact_url_hides_credentials_only(url: str, shown: str) -> None:
    assert redact_url(url) == shown


def test_redact_url_accepts_webcam_indexes() -> None:
    assert redact_url(0) == "0"


def test_redact_url_handles_a_password_with_an_at_sign() -> None:
    # Not percent-encoded: everything up to the last "@" before the host is userinfo.
    assert redact_url("rtsp://admin:p@ss@10.0.0.5/stream1") == "rtsp://admin:***@10.0.0.5/stream1"


def test_redact_text_masks_every_url_inside_a_message() -> None:
    from aivee_edge.redact import redact_text

    text = "cannot open rtsp://admin:s3cr3t@10.0.0.5/stream1 (or rtsp://u:p@h/x): timeout"
    assert redact_text(text) == (
        "cannot open rtsp://admin:***@10.0.0.5/stream1 (or rtsp://u:***@h/x): timeout"
    )
    assert redact_text("no models in models/") == "no models in models/"
