"""API test doubles. Unit tests use them without a DB; integration tests add `sessions`."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.edge.sync import EdgeSync, LoggingEdgeCommands
from aivee_api.rules.translator import RuleDraft, TranslationError
from aivee_api.settings import ApiSettings
from aivee_api.staff.enrol import Enroller, Upload
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Condition


def unattended_draft(**overrides: Any) -> RuleDraft:
    data: dict[str, Any] = {
        "understood": True,
        "clarification_ro": "",
        "name": "Masă neservită 2 min",
        "zone_tag": "table",
        "all_of": [
            Condition(kind="present", role="guest", min_duration_s=60),
            Condition(kind="absent", role="staff", min_duration_s=120),
        ],
        "cooldown_s": 300,
        "explanation_ro": "Te anunț când nimeni nu vine la masă de 2 minute.",
    }
    return RuleDraft(**{**data, **overrides})


class FakeTranslator:
    def __init__(self, draft: RuleDraft | None = None, error: TranslationError | None = None):
        self.draft = draft or unattended_draft()
        self.error = error
        self.calls: list[tuple[str, list[Zone]]] = []

    async def translate(self, text: str, zones: Sequence[Zone]) -> RuleDraft:
        self.calls.append((text, list(zones)))
        if self.error:
            raise self.error
        return self.draft


class OneHotEmbedder:
    """Embeds a crop (an int here) as a 512-d one-hot vector scaled by 3 (not normalised)."""

    def embed(self, crop: Any) -> list[float]:
        vec = [0.0] * 512
        vec[int(crop) % 512] = 3.0
        return vec


class ListDecoder:
    """Frames are the upload's bytes as ints; a video yields one frame per byte."""

    def frames(self, upload: Upload) -> list[Any]:
        return list(upload.data) if upload.is_video else [upload.data[0]]


class EvenCropper:
    """Finds a person only in even frames."""

    def crops(self, frame: Any) -> list[Any]:
        return [frame] if int(frame) % 2 == 0 else []


@pytest.fixture
def fake_enroller() -> Enroller:
    return Enroller(ListDecoder(), EvenCropper(), OneHotEmbedder())


@pytest.fixture
def settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        site="test", device="edge-01", snapshot_dir=tmp_path / "snapshots", mqtt_enabled=False
    )


@pytest.fixture
def publisher() -> RecordingPublisher:
    return RecordingPublisher()


@pytest.fixture
def translator() -> FakeTranslator:
    return FakeTranslator()


def make_services(
    settings: ApiSettings,
    sessions: Any,
    publisher: RecordingPublisher,
    translator: FakeTranslator,
    enroller: Enroller | None = None,
) -> Services:
    settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
    return Services(
        settings=settings,
        sessions=sessions,
        sync=EdgeSync(sessions, publisher, settings.site, settings.device),
        translator=translator,
        commands=LoggingEdgeCommands(),
        enroller=enroller,
    )


@pytest.fixture
def services_factory() -> Any:
    return make_services


@pytest.fixture
def draft_factory() -> Any:
    return unattended_draft


@pytest.fixture
def translator_factory() -> Any:
    return FakeTranslator
