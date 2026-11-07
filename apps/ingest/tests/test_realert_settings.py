import pytest
from aivee_ingest.config import IngestSettings


def test_realert_delay_defaults_to_two_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALERT_AFTER_S", raising=False)
    settings = IngestSettings()
    assert settings.realert_after_s == 120
    assert 0 < settings.realert_interval_s <= 10


def test_realert_delay_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REALERT_AFTER_S", "45")
    assert IngestSettings().realert_after_s == 45
