"""`make seed`: the demo organization, location and users (idempotent).

    python -m aivee_api.accounts.seed [--env-file .env]

Org "AiVee Demo" → location `demo` ("Terasa demo", restaurant) → owner@, manager@ and
staff@aivee.demo, all with the password in DEMO_PASSWORD. When DEMO_PASSWORD is empty, a
random one is generated and written into the env file. The password is never printed.
Re-running resets the three users' password, roles and the location's org/name/type.
"""

import argparse
import asyncio
import os
import secrets
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import Membership, Organization, User
from aivee_api.auth.passwords import MIN_PASSWORD_LENGTH, hash_password
from aivee_api.db.models import Site
from aivee_api.db.session import make_engine, make_session_factory

DEMO_ORG_ID = "org-demo"  # the same id 0003_auth_tenancy gives the migrated demo site
DEMO_ORG_NAME = "AiVee Demo"
DEMO_LOCATION = ("demo", "Terasa demo", "restaurant")
DEMO_USERS = (
    ("u-demo-owner", "owner@aivee.demo", "Olga Proprietar", None),
    ("u-demo-manager", "manager@aivee.demo", "Mihai Manager", "manager"),
    ("u-demo-staff", "staff@aivee.demo", "Ana Ospătar", "staff"),
)
VAR = "DEMO_PASSWORD"


def ensure_demo_password(env_file: Path | None, environ: Mapping[str, str]) -> str:
    """DEMO_PASSWORD from the environment, else a new one saved into `env_file`."""
    current = environ.get(VAR, "")
    if current:
        if len(current) < MIN_PASSWORD_LENGTH:
            raise SystemExit(f"{VAR} must have at least {MIN_PASSWORD_LENGTH} characters")
        return current
    if env_file is None:
        raise SystemExit(f"{VAR} is not set; pass --env-file to generate one")
    password = secrets.token_urlsafe(12)
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    kept = [line for line in lines if not line.startswith(f"{VAR}=")]
    kept.append(f"{VAR}={password}")
    # Write through a symlinked .env (worktrees) instead of replacing the link.
    target = env_file.resolve()
    target.write_text("\n".join(kept) + "\n")
    os.chmod(target, 0o600)
    return password


@dataclass(frozen=True)
class SeedResult:
    org_id: str
    location_id: str
    users: int


async def seed(s: AsyncSession, password: str) -> SeedResult:
    org = await s.get(Organization, DEMO_ORG_ID)
    if org is None:
        s.add(Organization(id=DEMO_ORG_ID, name=DEMO_ORG_NAME))
        await s.flush()
    loc_id, loc_name, loc_type = DEMO_LOCATION
    site = await s.get(Site, loc_id)
    if site is None:
        site = Site(id=loc_id)
        s.add(site)
    site.org_id, site.name, site.type = DEMO_ORG_ID, loc_name, loc_type
    await s.flush()

    pw_hash = hash_password(password)
    for user_id, email, name, role in DEMO_USERS:
        user = await s.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(id=user_id, email=email, org_id=DEMO_ORG_ID)
            s.add(user)
        user.org_id, user.name, user.password_hash = DEMO_ORG_ID, name, pw_hash
        user.is_owner = role is None
        await s.flush()
        membership = await s.get(Membership, (user.id, loc_id))
        if role is None:
            if membership is not None:
                await s.delete(membership)
        elif membership is None:
            s.add(Membership(user_id=user.id, location_id=loc_id, role=role))
        else:
            membership.role = role
    await s.commit()
    return SeedResult(DEMO_ORG_ID, loc_id, len(DEMO_USERS))


async def _run(password: str) -> SeedResult:
    engine = make_engine()
    try:
        async with make_session_factory(engine)() as s:
            return await seed(s, password)
    finally:
        await engine.dispose()


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args(argv)
    password = ensure_demo_password(args.env_file, os.environ)
    result = asyncio.run(_run(password))
    emails = ", ".join(u[1] for u in DEMO_USERS)
    print(
        f"seeded {result.org_id} / location {result.location_id}: {emails} "
        f"(password: {VAR} in your env file)"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
