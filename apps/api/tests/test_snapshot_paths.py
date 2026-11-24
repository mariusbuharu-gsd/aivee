"""S4: snapshot files are keyed by site and device, and served only from a row's stored path."""

from pathlib import Path

import pytest
from aivee_api.errors import NotFound
from aivee_api.events.service import snapshot_file, snapshot_key


def test_key_is_site_device_and_id() -> None:
    assert snapshot_key("loc-a", "edge-a", "ev-1") == "loc-a/edge-a/ev-1.jpg"


@pytest.mark.parametrize(
    ("site", "device", "snapshot_id"),
    [("..", "d", "e"), ("s", "..", "e"), ("s", "d", "../e"), ("s/x", "d", "e"), ("s", "d", "")],
)
def test_unsafe_segments_have_no_key(site: str, device: str, snapshot_id: str) -> None:
    assert snapshot_key(site, device, snapshot_id) is None


def test_serves_keyed_and_legacy_flat_paths(tmp_path: Path) -> None:
    (tmp_path / "loc-a" / "edge-a").mkdir(parents=True)
    (tmp_path / "loc-a" / "edge-a" / "ev-1.jpg").write_bytes(b"keyed")
    (tmp_path / "ev-0.jpg").write_bytes(b"flat")
    assert snapshot_file(tmp_path, "loc-a/edge-a/ev-1.jpg").read_bytes() == b"keyed"
    assert snapshot_file(tmp_path, "ev-0.jpg").read_bytes() == b"flat"


@pytest.mark.parametrize(
    "stored",
    [None, "", "../ev-0.jpg", "loc-a/../ev-0.jpg", "/etc/passwd", "ev-0.png", "a/ev-0.jpg"],
)
def test_rejects_missing_or_unsafe_stored_paths(tmp_path: Path, stored: str | None) -> None:
    (tmp_path / "ev-0.jpg").write_bytes(b"flat")
    with pytest.raises(NotFound):
        snapshot_file(tmp_path, stored)
