"""Host API and ingest containers must read and write the same snapshot directory."""

from pathlib import Path

import pytest
import yaml
from aivee_api.settings import ApiSettings
from aivee_ingest.config import IngestSettings

REPO = Path(__file__).resolve().parents[3]
SHARED = Path("data/snapshots")


def _compose() -> dict[str, dict[str, dict[str, object]]]:
    data = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    assert isinstance(data, dict)
    return data


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAPSHOT_DIR", raising=False)


def test_host_defaults_are_the_shared_repo_dir() -> None:
    assert ApiSettings().snapshot_dir == SHARED
    assert IngestSettings().snapshot_dir == SHARED


@pytest.mark.parametrize("service", ["ingest", "api"])
def test_compose_bind_mounts_the_shared_dir_at_snapshot_dir(service: str) -> None:
    svc = _compose()["services"][service]
    env = svc["environment"]
    assert isinstance(env, dict)
    mounts = svc["volumes"]
    assert isinstance(mounts, list)
    assert f"./{SHARED}:{env['SNAPSHOT_DIR']}" in mounts


def test_compose_has_no_snapshot_volume() -> None:
    assert "snapshots" not in (_compose().get("volumes") or {})
