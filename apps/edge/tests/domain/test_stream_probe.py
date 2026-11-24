"""Why a camera does not stream, the pure part: one RTSP DESCRIBE (or HTTP GET), the
camera's status, and Basic/Digest authentication."""

import hashlib

import pytest
from aivee_edge.domain.stream_probe import (
    StreamTarget,
    authorization,
    parse_response,
    request,
    verdict,
)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def test_target_splits_the_credentials_off_the_url() -> None:
    t = StreamTarget.parse("rtsp://admin:p%40ss@192.168.1.21:554/stream2")
    assert t is not None
    assert (t.scheme, t.host, t.port, t.user, t.password) == (
        "rtsp",
        "192.168.1.21",
        554,
        "admin",
        "p@ss",
    )
    assert t.uri == "rtsp://192.168.1.21:554/stream2"
    assert t.path == "/stream2"
    d = StreamTarget.parse("rtsp://192.168.1.30/cam/realmonitor?channel=1&subtype=1")
    assert d is not None and d.port == 554 and d.user is None
    assert d.uri == "rtsp://192.168.1.30:554/cam/realmonitor?channel=1&subtype=1"
    h = StreamTarget.parse("http://cam.local/video")
    assert h is not None and (h.port, h.path) == (80, "/video")
    assert StreamTarget.parse("0") is None
    assert StreamTarget.parse("rtsp://") is None


def test_rtsp_describe_and_http_get_requests() -> None:
    rtsp = StreamTarget.parse("rtsp://u:p@10.0.0.5/stream2")
    assert rtsp is not None
    text = request(rtsp, cseq=2, auth='Digest username="u"').decode()
    assert text.startswith("DESCRIBE rtsp://10.0.0.5:554/stream2 RTSP/1.0\r\n")
    assert "CSeq: 2\r\n" in text and 'Authorization: Digest username="u"\r\n' in text
    assert text.endswith("\r\n\r\n") and "u:p@" not in text
    http = StreamTarget.parse("http://10.0.0.6:8080/video?x=1")
    assert http is not None
    assert request(http, cseq=1).decode().startswith("GET /video?x=1 HTTP/1.1\r\nHost: 10.0.0.6")


def test_parse_response_reads_status_and_challenges() -> None:
    raw = (
        b"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n"
        b'WWW-Authenticate: Digest realm="4419b63f5e51", nonce="8b8d4e1f", stale="FALSE"\r\n'
        b'WWW-Authenticate: Basic realm="4419b63f5e51"\r\n\r\n'
    )
    r = parse_response(raw)
    assert r is not None and r.status == 401
    assert r.challenges == [
        'Digest realm="4419b63f5e51", nonce="8b8d4e1f", stale="FALSE"',
        'Basic realm="4419b63f5e51"',
    ]
    ok = parse_response(b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace\r\n\r\n")
    assert ok is not None and ok.status == 200
    assert parse_response(b"") is None
    assert parse_response(b"SSH-2.0-OpenSSH_9.6\r\n") is None


def test_digest_authorization_follows_rfc_2617() -> None:
    challenge = 'Digest realm="IP Camera", nonce="abc123", algorithm="MD5"'
    header = authorization([challenge], "admin", "pw", "DESCRIBE", "rtsp://h:554/s")
    ha1, ha2 = _md5("admin:IP Camera:pw"), _md5("DESCRIBE:rtsp://h:554/s")
    assert header is not None and header.startswith("Digest ")
    assert f'response="{_md5(f"{ha1}:abc123:{ha2}")}"' in header
    assert 'uri="rtsp://h:554/s"' in header and 'username="admin"' in header


def test_digest_names_the_algorithm_only_when_the_camera_did() -> None:
    # Tapo C310 answers 401 to a Digest that adds `algorithm=MD5` to a challenge without one.
    tapo = 'Digest realm="TP-LINK IP-Camera", nonce="92782960"'
    header = authorization(
        ['Basic realm="TP-LINK IP-Camera"', tapo], "u", "p", "DESCRIBE", "rtsp://h:554/s"
    )
    assert header is not None and header.startswith("Digest ") and "algorithm" not in header
    named = 'Digest realm="r", nonce="n", algorithm="MD5"'
    assert "algorithm=MD5" in (authorization([named], "u", "p", "DESCRIBE", "rtsp://h/s") or "")


def test_digest_with_qop_auth_uses_a_client_nonce() -> None:
    challenge = 'Digest realm="r", nonce="n", qop="auth,auth-int", opaque="o"'
    header = authorization([challenge], "u", "p", "GET", "/video", cnonce="c0ffee")
    ha1, ha2 = _md5("u:r:p"), _md5("GET:/video")
    assert header is not None
    assert f'response="{_md5(f"{ha1}:n:00000001:c0ffee:auth:{ha2}")}"' in header
    assert "qop=auth" in header and 'cnonce="c0ffee"' in header and 'opaque="o"' in header


def test_basic_when_the_camera_offers_only_basic() -> None:
    assert authorization(['Basic realm="cam"'], "admin", "pw", "GET", "/") == "Basic YWRtaW46cHc="
    assert authorization(['Bearer realm="x"'], "admin", "pw", "GET", "/") is None
    assert authorization([], "admin", "pw", "GET", "/") is None


@pytest.mark.parametrize(
    ("status", "answer"),
    [
        (200, "ok"),
        (401, "auth"),
        (403, "auth"),
        (404, "no_stream"),
        (454, "no_stream"),  # RTSP: Session Not Found
        (400, "unknown"),
        (500, "unknown"),
    ],
)
def test_verdict(status: int, answer: str) -> None:
    assert verdict(status) == answer
