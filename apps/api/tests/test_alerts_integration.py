"""Alert lifecycle endpoints against a real Postgres: ack, folded view, metrics, live feed."""

import json
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from aivee_api.accounts.models import Membership, Organization, User
from aivee_api.alerts.audit import AlertAuditEntry, get_audit_writer
from aivee_api.alerts.live import AlertFeed
from aivee_api.alerts.repository import AlertRepository
from aivee_api.auth.passwords import hash_password
from aivee_api.db.models import Site
from aivee_api.db.repositories import CameraRepository, DeviceRepository, EventRepository
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.events.service import LiveFeed
from aivee_api.main import create_app
from aivee_api.push.repository import PushSubscriptionRepository
from aivee_api.push.sender import Subscription
from aivee_api.settings import ApiSettings
from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import CameraConfig, Zone
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PASSWORD = "parola-alerte-1"
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[AlertAuditEntry] = []

    async def append(self, session: AsyncSession, entry: AlertAuditEntry) -> None:
        self.entries.append(entry)


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit()


@pytest.fixture
def app(
    settings: ApiSettings, sessions: Any, translator: Any, services_factory: Any, audit: Any
) -> FastAPI:
    services: Services = services_factory(settings, sessions, RecordingPublisher(), translator)
    app = create_app(services)
    app.dependency_overrides[get_audit_writer] = lambda: audit
    return app


USERS = {
    # email: (id, name, owner, staff location)
    "olga@a.ro": ("u-olga", "Olga", True, None),
    "ana@a.ro": ("u-ana", "Ana", False, "demo"),
    "ion@a.ro": ("u-ion", "Ion", False, "demo"),
    "otto@a.ro": ("u-otto", "Otto", False, "other"),
}


@pytest.fixture(autouse=True)
async def tenancy(sessions: Any) -> None:
    """org-a: locations `demo` and `other`; Olga owns it, Ana and Ion serve at `demo`,
    Otto at `other`."""
    pw = hash_password(PASSWORD)
    async with sessions() as s:
        s.add(Organization(id="org-a", name="Org A"))
        s.add_all(
            [
                Site(id="demo", name="Sala", org_id="org-a", type="restaurant"),
                Site(id="other", name="Terasa", org_id="org-a", type="terrace"),
            ]
        )
        await s.flush()
        for email, (uid, name, owner, _) in USERS.items():
            s.add(
                User(
                    id=uid, org_id="org-a", email=email, name=name, password_hash=pw, is_owner=owner
                )
            )
        await s.flush()
        for uid, _, _, loc in USERS.values():
            if loc:
                s.add(Membership(user_id=uid, location_id=loc, role="staff"))
        await s.commit()


Client = Callable[[str], Any]


@pytest.fixture
async def client_as(app: FastAPI, login: Any) -> AsyncIterator[Client]:
    """`await client_as("ana@a.ro")`: a logged-in client (its own cookie jar)."""
    clients: list[httpx.AsyncClient] = []

    async def make(email: str) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        await login(client, email, PASSWORD)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest.fixture
async def api(client_as: Client) -> httpx.AsyncClient:
    """The owner: sees every location of the organization."""
    client: httpx.AsyncClient = await client_as("olga@a.ro")
    return client


def _event(state: str, seconds: float, zone: str = "t1", rule: str = "r1") -> AlertEvent:
    return AlertEvent.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "rule_id": rule,
            "camera_id": "cam1",
            "zone_id": zone,
            "state": state,
            "at": T0 + timedelta(seconds=seconds),
            "summary_ro": "Masa 1: neservită de 1 min",
        }
    )


async def _ingest(sessions: Any, event: AlertEvent, device: str = "edge-01") -> None:
    """What aivee_ingest does with one event (store, then fold into its alert)."""
    async with sessions() as s:
        await DeviceRepository(s).ensure_device("demo" if device == "edge-01" else "other", device)
        assert await EventRepository(s).insert_if_new(event, device)
        await AlertRepository(s).link(event, device)
        await s.commit()


@pytest.fixture
async def camera(sessions: Any) -> None:
    async with sessions() as s:
        await DeviceRepository(s).ensure_device("demo", "edge-01")
        zone = Zone(id="t1", name="Masa Unu", tag="table", polygon=[(0, 0), (1, 0), (1, 1)])
        await CameraRepository(s).upsert(
            CameraConfig(id="cam1", name="Sala", source="0", zones=[zone]), "edge-01"
        )
        await s.commit()


async def test_lifecycle_opened_ack_arrived_closed(
    api: httpx.AsyncClient, client_as: Client, sessions: Any, camera: None, audit: RecordingAudit
) -> None:
    ana, ion = await client_as("ana@a.ro"), await client_as("ion@a.ro")
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    [view] = (await api.get("/api/alerts")).json()
    assert view["event_id"] == opened.event_id
    assert (view["state"], view["location_id"], view["zone_name"]) == ("opened", "demo", "Masa Unu")
    assert view["wait_s"] is None and view["acknowledged_by"] is None

    r = await ana.post(f"/api/alerts/{opened.event_id}/ack")
    assert r.status_code == 200, r.text
    acked = r.json()
    assert acked["state"] == "acknowledged"
    assert (acked["acknowledged_by"], acked["acknowledged_by_id"]) == ("Ana", "u-ana")
    assert acked["reaction_s"] is not None
    assert [e.kind for e in audit.entries] == ["alert.acknowledged"]
    assert audit.entries[0].summary_ro == "Ana a preluat alerta de la Masa Unu"
    assert (audit.entries[0].actor_kind, audit.entries[0].location_id) == ("user", "demo")
    assert audit.entries[0].actor_id == "u-ana"

    again = await ion.post(f"/api/alerts/{opened.event_id}/ack")
    assert again.status_code == 409
    assert again.json()["detail"] == {
        "code": "already_acknowledged",
        "message_ro": "Alerta a fost deja preluată de Ana.",
    }

    ack_at = datetime.fromisoformat(acked["acknowledged_at"])
    arrived_at = ack_at + timedelta(seconds=40)
    arrived = _event("arrived", (arrived_at - T0).total_seconds())
    closed = _event("closed", (arrived_at - T0).total_seconds())
    await _ingest(sessions, arrived)
    await _ingest(sessions, closed)

    [view] = (await api.get("/api/alerts")).json()
    reaction = (ack_at - T0).total_seconds()
    assert view["state"] == "closed"
    assert view["wait_s"] == pytest.approx(reaction + 40, abs=0.1)
    assert view["reaction_s"] == pytest.approx(reaction, abs=0.1)
    assert view["travel_s"] == 40
    assert not view["unacknowledged_arrival"]

    late = await api.post(f"/api/alerts/{opened.event_id}/ack")
    assert late.status_code == 409 and late.json()["detail"]["code"] == "alert_closed"


async def test_ack_of_a_closed_alert_is_409_and_unknown_is_404(
    api: httpx.AsyncClient, sessions: Any
) -> None:
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    await _ingest(sessions, _event("closed", 20))
    r = await api.post(f"/api/alerts/{opened.event_id}/ack")
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "alert_closed", "message_ro": "Alerta s-a închis deja."}
    assert (await api.post("/api/alerts/nope/ack")).status_code == 404


async def test_ack_in_another_location_is_404(api: httpx.AsyncClient, sessions: Any) -> None:
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    url = f"/api/alerts/{opened.event_id}/ack"
    assert (await api.post(url, params={"location_id": "other"})).status_code == 404
    assert (await api.post(url, params={"location_id": "demo"})).status_code == 200


async def test_arrival_without_ack_and_list_filters(api: httpx.AsyncClient, sessions: Any) -> None:
    a = _event("opened", 0, zone="t1")
    b = _event("opened", 10, zone="t2")
    c = _event("opened", 20, zone="t3", rule="r2")
    for e in (a, b, c):
        await _ingest(sessions, e)
    await _ingest(sessions, _event("arrived", 30, zone="t1"))
    await _ingest(sessions, _event("closed", 31, zone="t1"))
    await _ingest(sessions, _event("arrived", 40, zone="t2"))
    await api.post(f"/api/alerts/{c.event_id}/ack")
    other = _event("opened", 5, zone="x")
    await _ingest(sessions, other, device="edge-99")

    def ids(r: httpx.Response) -> list[str]:
        assert r.status_code == 200, r.text
        return [v["event_id"] for v in r.json()]

    assert ids(await api.get("/api/alerts")) == [c.event_id, b.event_id, other.event_id, a.event_id]
    assert ids(await api.get("/api/alerts?location_id=demo&limit=2")) == [c.event_id, b.event_id]
    assert ids(await api.get("/api/alerts?state=open&location_id=demo")) == [
        c.event_id,
        b.event_id,
    ]
    assert ids(await api.get("/api/alerts?state=closed")) == [a.event_id]
    assert ids(await api.get("/api/alerts?state=arrived")) == [b.event_id]
    assert ids(await api.get("/api/alerts?state=acknowledged")) == [c.event_id]
    assert ids(await api.get("/api/alerts?state=opened")) == [other.event_id]
    assert (await api.get("/api/alerts?state=bogus")).status_code == 422

    [view_a] = [v for v in (await api.get("/api/alerts")).json() if v["event_id"] == a.event_id]
    assert (view_a["wait_s"], view_a["reaction_s"], view_a["travel_s"]) == (30, None, None)
    assert view_a["unacknowledged_arrival"]
    # No camera config: the name comes from the summary.
    assert view_a["zone_name"] == "Masa 1"


async def test_view_access_limits_locations(client_as: Client, sessions: Any) -> None:
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    await _ingest(sessions, _event("opened", 5, zone="x"), device="edge-99")

    otto = await client_as("otto@a.ro")
    views = (await otto.get("/api/alerts")).json()
    assert [v["location_id"] for v in views] == ["other"]
    assert (await otto.get("/api/alerts?location_id=demo")).status_code == 404
    assert (await otto.post(f"/api/alerts/{opened.event_id}/ack")).status_code == 404
    m = await otto.get("/api/metrics/service", params={"location_id": "demo"})
    assert m.status_code == 404


async def test_alerts_need_a_session(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as anon:
        assert (await anon.get("/api/alerts")).status_code == 401
        assert (await anon.post("/api/alerts/x/ack")).status_code == 401


async def test_the_ack_writes_the_real_audit_log(
    settings: ApiSettings, sessions: Any, translator: Any, services_factory: Any, login: Any
) -> None:
    services: Services = services_factory(settings, sessions, RecordingPublisher(), translator)
    app = create_app(services)  # no writer override: RepositoryAuditWriter
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ana:
        await login(ana, "ana@a.ro", PASSWORD)
        assert (await ana.post(f"/api/alerts/{opened.event_id}/ack")).status_code == 200
        [row] = (await ana.get("/api/audit", params={"kind": "alert"})).json()["items"]
    assert (row["kind"], row["actor"]["id"], row["location_id"]) == (
        "alert.acknowledged",
        "u-ana",
        "demo",
    )
    assert row["summary_ro"] == "Ana a preluat alerta de la Masa 1"


async def test_service_metrics(api: httpx.AsyncClient, sessions: Any) -> None:
    for i, (arrive, close) in enumerate([(60, 60), (90, 90), (120, 120)]):
        await _ingest(sessions, _event("opened", i * 200, zone=f"z{i}"))
        await _ingest(sessions, _event("arrived", i * 200 + arrive, zone=f"z{i}"))
        await _ingest(sessions, _event("closed", i * 200 + close, zone=f"z{i}"))
    old = T0 - timedelta(days=3)
    await _ingest(sessions, _event("opened", (old - T0).total_seconds(), zone="old"))

    r = await api.get("/api/metrics/service", params={"location_id": "demo"})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["location_id"] == "demo" and "from" in m and "to" in m
    assert (m["alerts"], m["unacknowledged_arrivals"]) == (3, 3)
    assert m["wait"] == {"count": 3, "median_s": 90, "p90_s": 114}
    assert m["reaction"] == {"count": 0, "median_s": None, "p90_s": None}

    since = (T0 + timedelta(seconds=150)).isoformat()
    m = (await api.get("/api/metrics/service", params={"from": since})).json()
    assert (m["alerts"], m["wait"]["median_s"]) == (2, 105)


async def test_alerts_and_events_page_with_before(api: httpx.AsyncClient, sessions: Any) -> None:
    """`before` (an ISO time) pages both lists: only rows strictly older than it."""
    a = _event("opened", 0, zone="t1")
    b = _event("opened", 10, zone="t2")
    c = _event("opened", 20, zone="t3")
    for e in (a, b, c):
        await _ingest(sessions, e)
    await _ingest(sessions, _event("closed", 30, zone="t1"))

    def ids(r: httpx.Response) -> list[str]:
        assert r.status_code == 200, r.text
        return [v["event_id"] for v in r.json()]

    first = (await api.get("/api/alerts?limit=2")).json()
    assert [v["event_id"] for v in first] == [c.event_id, b.event_id]
    older = await api.get("/api/alerts", params={"limit": 2, "before": first[-1]["opened_at"]})
    assert ids(older) == [a.event_id]

    page = (await api.get("/api/events?limit=2")).json()
    assert [e["state"] for e in page] == ["closed", "opened"]
    rest = await api.get("/api/events", params={"before": page[-1]["at"]})
    assert ids(rest) == [b.event_id, a.event_id]
    assert (await api.get("/api/events?before=yesterday")).status_code == 422


async def test_live_feed_pushes_folded_alerts_and_keeps_raw_events_legacy(
    api: httpx.AsyncClient, client_as: Client, sessions: Any
) -> None:
    feed, raw = AlertFeed(sessions), LiveFeed(sessions)
    await feed.start()
    await raw.start()
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    [m] = await feed.poll()
    assert (m.type, m.data.event_id, m.data.state) == ("alert", opened.event_id, "opened")
    assert [r.data.state for r in await raw.poll()] == ["opened"]  # type: ignore[attr-defined]

    ana = await client_as("ana@a.ro")
    await ana.post(f"/api/alerts/{opened.event_id}/ack")
    [m] = await feed.poll()
    assert m.data.state == "acknowledged" and m.data.acknowledged_by
    assert await feed.poll() == []

    await _ingest(sessions, _event("arrived", 50))
    await _ingest(sessions, _event("closed", 50))
    [m] = await feed.poll()
    assert (m.data.state, m.data.event_id) == ("closed", opened.event_id)
    assert m.data.arrived_at is not None
    # The raw stream (what today's dashboard folds) never shows `arrived`.
    assert [r.data.state for r in await raw.poll()] == ["closed"]  # type: ignore[attr-defined]
    assert [e["state"] for e in (await api.get("/api/events")).json()] == ["closed", "opened"]


class FakePushSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def send(self, sub: Any, payload: str) -> int:
        self.sent.append((sub.endpoint, json.loads(payload)))
        return 201


async def test_ack_replaces_the_alert_push_on_every_phone_with_who_goes(
    app: FastAPI, client_as: Client, sessions: Any, camera: None
) -> None:
    """Q5: "Merg eu" stops the alarm on all phones (same tag = the alert's notification is
    replaced, silently) and shows who goes."""
    sender = FakePushSender()
    app.state.push_sender = sender
    async with sessions() as s:
        repo = PushSubscriptionRepository(s)
        await repo.upsert(Subscription("https://push.example/ion", "k", "a"), user_id="u-ion")
        await repo.upsert(Subscription("https://push.example/otto", "k", "a"), user_id="u-otto")
        await s.commit()
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    ana, ion = await client_as("ana@a.ro"), await client_as("ion@a.ro")

    assert (await ana.post(f"/api/alerts/{opened.event_id}/ack")).status_code == 200
    [(endpoint, payload)] = sender.sent  # the location's phones only, not Otto's
    assert endpoint == "https://push.example/ion"
    assert payload["tag"] == opened.event_id
    assert payload["body"] == "Ana merge la Masa Unu"
    assert payload["title"] == "AiVee · Preluată"
    assert payload["kind"] == "ack"  # the service worker replaces it silently

    assert (await ion.post(f"/api/alerts/{opened.event_id}/ack")).status_code == 409
    assert len(sender.sent) == 1  # a refused ack pushes nothing


async def test_ack_without_push_configured_still_works(
    client_as: Client, sessions: Any, camera: None
) -> None:
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    ana = await client_as("ana@a.ro")
    assert (await ana.post(f"/api/alerts/{opened.event_id}/ack")).status_code == 200
