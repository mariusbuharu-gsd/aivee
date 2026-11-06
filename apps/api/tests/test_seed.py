"""`make seed`: DEMO_PASSWORD handling (unit) and idempotent seeding (integration)."""

from pathlib import Path
from typing import Any

import pytest
from aivee_api.accounts.models import Membership, Organization, User
from aivee_api.accounts.seed import ensure_demo_password, seed
from aivee_api.auth.passwords import verify_password
from aivee_api.db.models import Site
from sqlalchemy import func, select


def test_existing_password_is_used_and_the_file_untouched(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    assert ensure_demo_password(env, {"DEMO_PASSWORD": "parola-demo"}) == "parola-demo"
    assert env.read_text() == "A=1\n"


def test_missing_password_is_generated_into_the_env_file_without_printing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\nDEMO_PASSWORD=\nB=2\n")
    password = ensure_demo_password(env, {})
    assert len(password) >= 12
    assert env.read_text() == f"A=1\nB=2\nDEMO_PASSWORD={password}\n"
    assert password not in capsys.readouterr().out + capsys.readouterr().err
    assert env.stat().st_mode & 0o777 == 0o600


def test_generation_writes_through_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.env"
    real.write_text("A=1\n")
    link = tmp_path / ".env"
    link.symlink_to(real)
    password = ensure_demo_password(link, {})
    assert link.is_symlink() and f"DEMO_PASSWORD={password}" in real.read_text()


def test_short_or_absent_password_is_refused() -> None:
    with pytest.raises(SystemExit):
        ensure_demo_password(None, {})
    with pytest.raises(SystemExit):
        ensure_demo_password(None, {"DEMO_PASSWORD": "short"})


@pytest.mark.integration
async def test_seed_is_idempotent_and_claims_the_demo_site(sessions: Any) -> None:
    async with sessions() as s:
        s.add(Site(id="demo", name="demo"))  # as ingest would have created it
        await s.commit()
    for password in ("parola-demo-1", "parola-demo-2"):
        async with sessions() as s:
            await seed(s, password)
    async with sessions() as s:
        assert await s.scalar(select(func.count()).select_from(Organization)) == 1
        site = await s.get(Site, "demo")
        assert site is not None and (site.org_id, site.name, site.type) == (
            "org-demo",
            "Terasa demo",
            "restaurant",
        )
        users = {u.email: u for u in await s.scalars(select(User))}
        assert set(users) == {"owner@aivee.demo", "manager@aivee.demo", "staff@aivee.demo"}
        assert users["owner@aivee.demo"].is_owner
        assert verify_password(users["staff@aivee.demo"].password_hash, "parola-demo-2")
        roles = {(m.user_id, m.role) for m in await s.scalars(select(Membership))}
        assert roles == {("u-demo-manager", "manager"), ("u-demo-staff", "staff")}
