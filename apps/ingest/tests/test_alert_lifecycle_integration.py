"""Fake edge → Mosquitto (production ACL) → ingest x2 → Postgres → API: the whole lifecycle.

The unattended scenario runs through the real edge pipeline on the wall clock (10x faster
than real time): the alert opens, a user acknowledges it through the API, the waiter
stays at Masa 1 for ARRIVE_S → arrived → closed. The folded view must show all of it.
"""

import asyncio
import importlib.util
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from aivee_api.alerts.audit import AlertAuditEntry, get_audit_writer
from aivee_api.db.repositories import DeviceRepository
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.edge.sync import EdgeSync, LoggingEdgeCommands
from aivee_api.main import create_app
from aivee_api.settings import ApiSettings
from aivee_contracts.events import AlertEvent
from aivee_edge.adapters.mqtt import MqttEdgeClient
from aivee_ingest.config import IngestSettings
from aivee_ingest.handler import IngestHandler
from aivee_ingest.worker import run_worker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

TOOL = Path(__file__).resolve().parents[3] / "tools" / "fake_edge.py"


def _load_fake_edge() -> ModuleType:
    if "fake_edge" in sys.modules:
        return sys.modules["fake_edge"]
    spec = importlib.util.spec_from_file_location("fake_edge", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["fake_edge"] = module
    spec.loader.exec_module(module)
    return module


fake_edge = _load_fake_edge()

SPEED = 10.0


class Notifier:
    def __init__(self) -> None:
        self.opened: list[AlertEvent] = []
        self.texts: list[str] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.opened.append(event)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None
    ) -> None:
        self.texts.append(text)


class Audit:
    def __init__(self) -> None:
        self.entries: list[AlertAuditEntry] = []

    async def append(self, session: AsyncSession, entry: AlertAuditEntry) -> None:
        self.entries.append(entry)


STAFF = "ana@life.ro"
PASSWORD = "parola-life-1"


async def _ana_serves_at(sessions: Any, site: str, device: str) -> None:
    """The test's location and device, and Ana (staff there, who logs in). Seeded before
    ingest subscribes, so retained statuses of earlier tests cannot claim the device."""
    from aivee_api.accounts.models import Membership, Organization, User
    from aivee_api.auth.passwords import hash_password
    from aivee_api.db.models import Site

    async with sessions() as s:
        s.add(Organization(id="org-life", name="Life"))
        await s.flush()
        s.add(Site(id=site, name="Locație", org_id="org-life"))
        s.add(
            User(
                id="u-ana",
                org_id="org-life",
                email=STAFF,
                name="Ana",
                password_hash=hash_password(PASSWORD),
            )
        )
        await s.flush()
        s.add(Membership(user_id="u-ana", location_id=site, role="staff"))
        await DeviceRepository(s).ensure_device(site, device)
        await s.commit()


@pytest.fixture
async def api(
    broker: Any,
    site: str,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    audit: Audit,
) -> AsyncIterator[httpx.AsyncClient]:
    """Logged in as Ana."""
    await _ana_serves_at(sessions, site, broker.edge[0])
    settings = ApiSettings(snapshot_dir=tmp_path / "api", mqtt_enabled=False)
    settings.snapshot_dir.mkdir()
    services = Services(
        settings=settings,
        sessions=sessions,
        sync=EdgeSync(sessions, RecordingPublisher(), settings.site, settings.device),
        translator=None,  # type: ignore[arg-type]
        commands=LoggingEdgeCommands(),
    )
    app = create_app(services)
    app.dependency_overrides[get_audit_writer] = lambda: audit
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = {"email": STAFF, "password": PASSWORD}
        assert (await client.post("/api/auth/login", json=login)).status_code == 200
        yield client


@pytest.fixture
def audit() -> Audit:
    return Audit()


async def test_fake_edge_alert_is_acknowledged_arrives_and_closes(
    broker: Any,
    sessions: async_sessionmaker[AsyncSession],
    site: str,
    tmp_path: Path,
    api: httpx.AsyncClient,
    audit: Audit,
) -> None:
    notifiers = [Notifier(), Notifier()]
    tasks = []
    for i, notifier in enumerate(notifiers):
        handler = IngestHandler(sessions, tmp_path / "snap", notifier, audit=audit)
        user, password = broker.ingest
        settings = IngestSettings(
            mqtt_host=broker.host,
            mqtt_port=broker.port,
            mqtt_ingest_user=user,
            mqtt_ingest_password=password,
            mqtt_client_id=f"ingest-life-{i}-{uuid.uuid4().hex[:6]}",
        )
        ready = asyncio.Event()
        tasks.append(asyncio.create_task(run_worker(settings, handler, ready)))
        await asyncio.wait_for(ready.wait(), 10)

    device, password = broker.edge
    edge = MqttEdgeClient(broker.host, broker.port, device, password, site, device)
    await asyncio.to_thread(edge.start)
    try:
        run = asyncio.create_task(
            asyncio.to_thread(
                fake_edge.run_scenario,
                fake_edge.SCENARIOS["unattended"],
                edge,
                fake_edge.FallbackConfig(edge, "cam-01", force_demo=True),
                device=device,
                camera_id="cam-01",
                speed=SPEED,
            )
        )

        async def alerts() -> list[dict[str, Any]]:
            r = await api.get("/api/alerts", params={"location_id": site})
            assert r.status_code == 200, r.text
            return list(r.json())

        async def until(state: str, timeout: float = 30) -> dict[str, Any]:
            async def poll() -> dict[str, Any]:
                while True:
                    views = await alerts()
                    if views and views[0]["state"] == state:
                        return views[0]
                    await asyncio.sleep(0.05)

            return await asyncio.wait_for(poll(), timeout)

        opened = await until("opened")
        assert opened["zone_name"] == "Masa 1" and opened["rule_id"] == "demo-unattended"
        r = await api.post(f"/api/alerts/{opened['event_id']}/ack")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "acknowledged"

        closed = await until("closed")
        await run
    finally:
        await asyncio.to_thread(edge.stop)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert closed["event_id"] == opened["event_id"]
    assert (closed["acknowledged_by"], closed["acknowledged_by_id"]) == ("Ana", "u-ana")
    assert closed["arrived_at"] is not None and not closed["unacknowledged_arrival"]
    # Simulated: opens at 60 s, the waiter stays at Masa 1 from 90 s → arrived at 95 s.
    expected_wait = 35 / SPEED
    # Wall-clock under a time-scaled edge: slow CI runners stretch it, so only bound it loosely.
    assert expected_wait - 0.4 <= closed["wait_s"] <= expected_wait * 2 + 1
    assert closed["reaction_s"] + closed["travel_s"] == pytest.approx(closed["wait_s"], abs=0.11)

    texts = [t for n in notifiers for t in n.texts]
    assert texts == [f"Ana a ajuns la Masa 1 după {round(closed['wait_s'])} s"]
    assert sum(len(n.opened) for n in notifiers) == 1
    kinds = sorted(e.kind for e in audit.entries)
    assert kinds == ["alert.acknowledged", "alert.arrived", "alert.closed", "alert.opened"]
    assert all(e.location_id for e in audit.entries)
