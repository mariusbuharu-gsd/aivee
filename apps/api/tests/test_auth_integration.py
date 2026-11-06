"""Register / login / logout / me against Postgres, with cookies like the dashboard uses."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from aivee_api.accounts.models import SessionRow
from aivee_api.auth.tokens import hash_token
from aivee_api.deps import Services
from aivee_api.main import create_app
from sqlalchemy import func, select, update

pytestmark = pytest.mark.integration


@pytest.fixture
def services(
    settings: Any, sessions: Any, publisher: Any, translator: Any, services_factory: Any
) -> Services:
    svc: Services = services_factory(settings, sessions, publisher, translator)
    return svc


@pytest.fixture
def client_factory(services: Services) -> Any:
    app = create_app(services)

    def make() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return make


@pytest.fixture
async def api(client_factory: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory() as c:
        yield c


REGISTER = {
    "org_name": "Bistro Ana",
    "name": "Ana Pop",
    "email": "Ana@Bistro.ro",
    "password": "parola-lunga",
}


async def test_register_creates_org_and_owner_and_logs_in(api: httpx.AsyncClient) -> None:
    r = await api.post("/api/auth/register", json=REGISTER)
    assert r.status_code == 201, r.text
    me = r.json()
    assert me["user"]["email"] == "ana@bistro.ro" and me["user"]["name"] == "Ana Pop"
    assert me["org"]["name"] == "Bistro Ana"
    assert me["is_owner"] is True and me["locations"] == []

    cookie = r.headers["set-cookie"]
    assert cookie.startswith("aivee_session=")
    for flag in ("HttpOnly", "Path=/", "SameSite=lax", "Max-Age=43200"):
        assert flag.lower() in cookie.lower()
    assert "secure" not in cookie.lower()

    assert (await api.get("/api/auth/me")).json() == me


@pytest.mark.parametrize(
    ("patch", "status"),
    [
        ({"password": "scurta"}, 422),
        ({"email": "nu-e-email"}, 422),
        ({"name": "  "}, 422),
        ({"org_name": ""}, 422),
    ],
)
async def test_register_validation_is_romanian(
    api: httpx.AsyncClient, patch: dict[str, str], status: int
) -> None:
    r = await api.post("/api/auth/register", json={**REGISTER, **patch})
    assert r.status_code == status
    assert r.json()["detail"]["code"] == "invalid" and r.json()["detail"]["message_ro"]


async def test_register_twice_is_409(client_factory: Any) -> None:
    async with client_factory() as a, client_factory() as b:
        assert (await a.post("/api/auth/register", json=REGISTER)).status_code == 201
        r = await b.post("/api/auth/register", json={**REGISTER, "email": "ana@bistro.ro"})
        assert r.status_code == 409


async def test_login_me_logout(api: httpx.AsyncClient, sessions: Any, tenancy_factory: Any) -> None:
    await tenancy_factory(sessions)
    assert (await api.get("/api/auth/me")).status_code == 401
    r = await api.post(
        "/api/auth/login", json={"email": "MANAGER@t.ro ", "password": "parola-test-1"}
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["is_owner"] is False
    [loc] = me["locations"]
    assert (loc["id"], loc["name"], loc["type"], loc["role"]) == (
        "test",
        "Terasa",
        "terrace",
        "manager",
    )
    assert "rules.manage" in loc["permissions"] and "locations.manage" not in loc["permissions"]

    token = api.cookies["aivee_session"]
    async with sessions() as s:
        row = await s.get(SessionRow, hash_token(token))
        assert row is not None  # stored hashed, never in clear
        assert (
            await s.scalar(
                select(func.count()).select_from(SessionRow).where(SessionRow.token_hash == token)
            )
            == 0
        )

    r = await api.post("/api/auth/logout")
    assert r.status_code == 204
    assert "aivee_session" not in api.cookies
    async with sessions() as s:
        assert await s.get(SessionRow, hash_token(token)) is None
    assert (await api.get("/api/auth/me")).status_code == 401
    api.cookies.set("aivee_session", token)  # a stolen, logged-out token is useless
    assert (await api.get("/api/auth/me")).status_code == 401


async def test_owner_sees_every_location_of_the_org(
    api: httpx.AsyncClient, sessions: Any, tenancy_factory: Any, login: Any
) -> None:
    await tenancy_factory(sessions)
    me = (await login(api, "owner@t.ro")).json()
    assert me["is_owner"] is True
    assert [(x["id"], x["role"]) for x in me["locations"]] == [
        ("test", "owner"),
        ("other", "owner"),
    ]  # never org-x's `far`
    assert "locations.manage" in me["locations"][0]["permissions"]


async def test_wrong_password_is_401_and_audited(
    api: httpx.AsyncClient, sessions: Any, tenancy_factory: Any
) -> None:
    await tenancy_factory(sessions)
    r = await api.post("/api/auth/login", json={"email": "staff@t.ro", "password": "gresit-123"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "unauthenticated"
    r = await api.post("/api/auth/login", json={"email": "nimeni@t.ro", "password": "gresit-123"})
    assert r.status_code == 401
    from aivee_api.audit.models import AuditRow

    async with sessions() as s:
        rows = (await s.scalars(select(AuditRow).order_by(AuditRow.id))).all()
    assert [(r.kind, r.actor_kind, r.org_id) for r in rows] == [
        ("auth.login_failed", "user", "org-t"),
        ("auth.login_failed", "system", None),
    ]
    assert rows[0].summary_ro == "Autentificare eșuată pentru staff@t.ro"


async def test_login_rate_limit(
    api: httpx.AsyncClient, sessions: Any, tenancy_factory: Any
) -> None:
    await tenancy_factory(sessions)
    bad = {"email": "staff@t.ro", "password": "gresit-123"}
    for _ in range(10):
        assert (await api.post("/api/auth/login", json=bad)).status_code == 401
    r = await api.post("/api/auth/login", json={**bad, "password": "parola-test-1"})
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "rate_limited"
    assert "încercări" in r.json()["detail"]["message_ro"]
    other = {"email": "manager@t.ro", "password": "parola-test-1"}
    assert (await api.post("/api/auth/login", json=other)).status_code == 200


async def test_session_slides_and_expires(
    api: httpx.AsyncClient, sessions: Any, tenancy_factory: Any, login: Any
) -> None:
    await tenancy_factory(sessions)
    await login(api, "staff@t.ro")
    token_hash = hash_token(api.cookies["aivee_session"])
    soon = datetime.now(UTC) + timedelta(hours=1)
    async with sessions() as s:
        await s.execute(
            update(SessionRow).where(SessionRow.token_hash == token_hash).values(expires_at=soon)
        )
        await s.commit()
    r = await api.get("/api/auth/me")
    assert r.status_code == 200 and "aivee_session=" in r.headers.get("set-cookie", "")
    async with sessions() as s:
        row = await s.get(SessionRow, token_hash)
        assert row is not None and row.expires_at > datetime.now(UTC) + timedelta(hours=11)
        await s.execute(
            update(SessionRow)
            .where(SessionRow.token_hash == token_hash)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert (await api.get("/api/auth/me")).status_code == 401


async def test_cors_allows_credentials_for_explicit_origins(api: httpx.AsyncClient) -> None:
    for origin in ("http://localhost:5173", "http://localhost:5174"):
        r = await api.options(
            "/api/auth/me",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert r.headers["access-control-allow-origin"] == origin
        assert r.headers["access-control-allow-credentials"] == "true"
    r = await api.options(
        "/api/auth/me",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in r.headers
