"""Alert lifecycle endpoints against a real Postgres: ack, folded view, metrics, live feed."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from aivee_api.alerts.audit import AlertAuditEntry, get_audit_writer
from aivee_api.alerts.auth import Access, DemoUser, require_view
from aivee_api.alerts.live import AlertFeed
from aivee_api.alerts.repository import AlertRepository
from aivee_api.db.repositories import CameraRepository, DeviceRepository, EventRepository
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.events.service import LiveFeed
from aivee_api.main import create_app
from aivee_api.settings import ApiSettings
from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import CameraConfig, Zone
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

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


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


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
    api: httpx.AsyncClient, sessions: Any, camera: None, audit: RecordingAudit
) -> None:
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    [view] = (await api.get("/api/alerts")).json()
    assert view["event_id"] == opened.event_id
    assert (view["state"], view["location_id"], view["zone_name"]) == ("opened", "demo", "Masa Unu")
    assert view["wait_s"] is None and view["acknowledged_by"] is None

    r = await api.post(f"/api/alerts/{opened.event_id}/ack", headers={"X-Demo-User": "Ana"})
    assert r.status_code == 200, r.text
    acked = r.json()
    assert acked["state"] == "acknowledged"
    assert acked["acknowledged_by"] == {"id": "demo-ana", "name": "Ana"}
    assert acked["reaction_s"] is not None
    assert [e.kind for e in audit.entries] == ["alert.acknowledged"]
    assert audit.entries[0].summary_ro == "Ana a preluat alerta de la Masa Unu"
    assert (audit.entries[0].actor_kind, audit.entries[0].location_id) == ("user", "demo")

    again = await api.post(f"/api/alerts/{opened.event_id}/ack", headers={"X-Demo-User": "Ion"})
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


async def test_view_access_limits_locations(
    app: FastAPI, api: httpx.AsyncClient, sessions: Any
) -> None:
    await _ingest(sessions, _event("opened", 0))
    await _ingest(sessions, _event("opened", 5, zone="x"), device="edge-99")

    async def only_other() -> Access:
        return Access(DemoUser("u1", "Ana"), frozenset({"other"}))

    app.dependency_overrides[require_view] = only_other
    views = (await api.get("/api/alerts")).json()
    assert [v["location_id"] for v in views] == ["other"]
    assert (await api.get("/api/alerts?location_id=demo")).status_code == 404


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


async def test_live_feed_pushes_folded_alerts_and_keeps_raw_events_legacy(
    api: httpx.AsyncClient, sessions: Any
) -> None:
    feed, raw = AlertFeed(sessions), LiveFeed(sessions)
    await feed.start()
    await raw.start()
    opened = _event("opened", 0)
    await _ingest(sessions, opened)
    [m] = await feed.poll()
    assert (m.type, m.data.event_id, m.data.state) == ("alert", opened.event_id, "opened")
    assert [r.data.state for r in await raw.poll()] == ["opened"]  # type: ignore[attr-defined]

    await api.post(f"/api/alerts/{opened.event_id}/ack", headers={"X-Demo-User": "Ana"})
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
