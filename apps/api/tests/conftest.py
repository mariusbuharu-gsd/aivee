"""API test doubles. Unit tests use them without a DB; integration tests add `sessions`."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
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

    def crops(self, frame: Any, largest_only: bool = False) -> list[Any]:
        return [frame] if int(frame) % 2 == 0 else []


class TagEncoder:
    """A "JPEG" thumbnail that just names the crop."""

    def jpeg(self, crop: Any, max_side: int) -> bytes:
        return b"\xff\xd8\xff" + f"crop-{crop}".encode()


@pytest.fixture
def fake_enroller() -> Enroller:
    return Enroller(ListDecoder(), EvenCropper(), OneHotEmbedder(), TagEncoder())


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


# --- accounts and tenancy (integration) ---------------------------------------------------

PASSWORD = "parola-test-1"


@dataclass(frozen=True)
class Tenancy:
    """org-t: locations `test` (= settings.site) and `other`; org-x: location `far`.
    Users (password PASSWORD): owner@t.ro, manager@t.ro (test), staff@t.ro (test),
    other@t.ro (manager of `other`), owner@x.ro."""

    org: str = "org-t"
    location: str = "test"
    other_location: str = "other"
    foreign_location: str = "far"


async def seed_tenancy(sessions: Any) -> Tenancy:
    from aivee_api.accounts.models import Membership, Organization, User
    from aivee_api.auth.passwords import hash_password
    from aivee_api.db.models import Site

    t = Tenancy()
    pw = hash_password(PASSWORD)
    async with sessions() as s:
        s.add_all([Organization(id="org-t", name="Org T"), Organization(id="org-x", name="Org X")])
        s.add(Site(id=t.location, name="Terasa", org_id="org-t", type="terrace"))
        await s.commit()  # `test` is created first, so it is everyone's default location
        s.add_all(
            [
                Site(id=t.other_location, name="Sala mare", org_id="org-t", type="restaurant"),
                Site(id=t.foreign_location, name="Străin", org_id="org-x", type="shop"),
            ]
        )
        await s.flush()
        users = [
            ("u-owner", "org-t", "owner@t.ro", "Olga", True),
            ("u-manager", "org-t", "manager@t.ro", "Mihai", False),
            ("u-staff", "org-t", "staff@t.ro", "Ana", False),
            ("u-other", "org-t", "other@t.ro", "Otilia", False),
            ("u-xowner", "org-x", "owner@x.ro", "Xenia", True),
        ]
        s.add_all(
            [
                User(id=i, org_id=o, email=e, name=n, password_hash=pw, is_owner=own)
                for i, o, e, n, own in users
            ]
        )
        await s.flush()
        s.add_all(
            [
                Membership(user_id="u-manager", location_id=t.location, role="manager"),
                Membership(user_id="u-staff", location_id=t.location, role="staff"),
                Membership(user_id="u-other", location_id=t.other_location, role="manager"),
            ]
        )
        await s.commit()
    return t


@pytest.fixture
def tenancy_factory() -> Any:
    return seed_tenancy


async def login_as(client: Any, email: str, password: str = PASSWORD) -> Any:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


@pytest.fixture
def login() -> Any:
    return login_as


@pytest.fixture
def services(
    settings: ApiSettings,
    sessions: Any,
    publisher: RecordingPublisher,
    translator: FakeTranslator,
) -> Services:
    """Integration services without enrolment models (test files may override this)."""
    return make_services(settings, sessions, publisher, translator)


@pytest.fixture
def client_factory(services: Services) -> Any:
    """`async with client_factory() as c:` — one cookie jar per simulated browser."""
    import httpx
    from aivee_api.main import create_app

    app = create_app(services)

    def make() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return make


@pytest.fixture
async def api(client_factory: Any) -> AsyncIterator[Any]:
    async with client_factory() as c:
        yield c
