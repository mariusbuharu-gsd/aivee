"""MQTT transport settings for a remote edge (MQTT over wss through the server's proxy)."""

import pytest
from aivee_edge.app import build_client
from aivee_edge.settings import EdgeSettings


@pytest.fixture(autouse=True)
def _no_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # The repo's .env must not leak into these tests.
    monkeypatch.setitem(EdgeSettings.model_config, "env_file", None)
    for name in ("MQTT_TRANSPORT", "MQTT_TLS", "MQTT_WS_PATH", "MQTT_HOST", "MQTT_PORT"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_keep_plain_tcp() -> None:
    s = EdgeSettings()
    assert (s.mqtt_transport, s.mqtt_tls, s.mqtt_ws_path) == ("tcp", False, "/mqtt")


def test_env_selects_websockets_over_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_TRANSPORT", "websockets")
    monkeypatch.setenv("MQTT_TLS", "true")
    monkeypatch.setenv("MQTT_WS_PATH", "/")
    monkeypatch.setenv("MQTT_HOST", "mqtt.example.com")
    monkeypatch.setenv("MQTT_PORT", "443")
    s = EdgeSettings()
    client = build_client(s)
    assert client._client._transport == "websockets"
    assert client._client._websocket_path == "/"
    assert client._client._ssl_context is not None


def test_bad_transport_fails_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_TRANSPORT", "udp")
    with pytest.raises(ValueError):
        EdgeSettings()
