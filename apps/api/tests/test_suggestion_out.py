"""A suggestion's photo URL on the API (pure, no DB)."""

from aivee_api.db.models import SuggestionRow
from aivee_api.events.schemas import suggestion_out


def _row(snapshot_path: str | None) -> SuggestionRow:
    return SuggestionRow(
        suggestion_id="s-7",
        device_id="edge-01",
        camera_id="cam1",
        track_id=7,
        staff_score=0.8,
        reason_ro="vizitează 3 mese",
        status="pending",
        snapshot_path=snapshot_path,
    )


def test_a_suggestion_with_a_crop_links_its_blurred_photo() -> None:
    out = suggestion_out(_row("s-7.jpg"))
    assert out.snapshot is True
    assert out.snapshot_url == "/api/snapshots/s-7"


def test_a_suggestion_without_a_crop_has_no_photo_url() -> None:
    out = suggestion_out(_row(None))
    assert out.snapshot is False
    assert out.snapshot_url is None
