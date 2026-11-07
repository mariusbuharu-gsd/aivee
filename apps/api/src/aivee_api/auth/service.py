"""Register, log in, log out. Every outcome is written to the audit history."""

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import Organization, SessionRow, User
from aivee_api.audit.repository import Actor, AuditRepository, Target
from aivee_api.auth.passwords import (
    DUMMY_HASH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    verify_password,
)
from aivee_api.auth.principal import Principal, load_principal
from aivee_api.auth.ratelimit import LoginRateLimiter, normalise_email
from aivee_api.auth.tokens import hash_token, new_token
from aivee_api.errors import Conflict, Invalid, RateLimited, Unauthenticated
from aivee_api.settings import ApiSettings

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BAD_LOGIN = "Email sau parolă greșită."
TOO_MANY = "Prea multe încercări eșuate. Încercați din nou peste 15 minute."


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def clean_email(email: str) -> str:
    email = normalise_email(email)
    if not _EMAIL.match(email):
        raise Invalid("Adresa de email nu este validă.")
    return email


def clean_name(name: str, what: str = "Numele") -> str:
    name = name.strip()
    if not name:
        raise Invalid(f"{what} este obligatoriu.")
    return name


def check_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Parola trebuie să aibă cel puțin {MIN_PASSWORD_LENGTH} caractere.")
    return password


async def email_taken(s: AsyncSession, email: str) -> bool:
    return bool(await s.scalar(select(func.count()).select_from(User).where(User.email == email)))


class AuthService:
    def __init__(
        self, session: AsyncSession, settings: ApiSettings, limiter: LoginRateLimiter
    ) -> None:
        self._s = session
        self._settings = settings
        self._limiter = limiter
        self._audit = AuditRepository(session)

    @property
    def _ttl(self) -> timedelta:
        return timedelta(hours=self._settings.session_ttl_hours)

    async def start_session(self, user: User) -> str:
        """Create a session row for `user` and return the cookie token (caller commits)."""
        now = datetime.now(UTC)
        await self._s.execute(
            delete(SessionRow).where(SessionRow.user_id == user.id, SessionRow.expires_at <= now)
        )
        token = new_token()
        self._s.add(
            SessionRow(token_hash=hash_token(token), user_id=user.id, expires_at=now + self._ttl)
        )
        await self._s.flush()
        return token

    async def register(
        self, org_name: str, name: str, email: str, password: str
    ) -> tuple[Principal, str]:
        org_name = clean_name(org_name, "Numele organizației")
        name = clean_name(name)
        email = clean_email(email)
        check_password(password)
        if await email_taken(self._s, email):
            raise Conflict("Există deja un cont cu acest email.")
        org = Organization(id=new_id("org"), name=org_name)
        self._s.add(org)
        await self._s.flush()
        user = User(
            id=new_id("u"),
            org_id=org.id,
            email=email,
            name=name,
            password_hash=hash_password(password),
            is_owner=True,
        )
        self._s.add(user)
        await self._s.flush()
        token = await self.start_session(user)
        await self._audit.append("auth.login", _actor(user), org_id=org.id)
        await self._s.commit()
        return await load_principal(self._s, user), token

    async def login(self, email: str, password: str) -> tuple[Principal, str]:
        email = normalise_email(email)
        if self._limiter.blocked(email):
            raise RateLimited(TOO_MANY)
        user = await self._s.scalar(select(User).where(User.email == email))
        if not verify_password(user.password_hash if user else DUMMY_HASH, password) or not user:
            self._limiter.failed(email)
            actor = _actor(user) if user else Actor("system", "anonymous", email[:200])
            await self._audit.append(
                "auth.login_failed",
                actor,
                org_id=user.org_id if user else None,
                target=Target("email", email[:128], email[:200]),
            )
            await self._s.commit()
            raise Unauthenticated(BAD_LOGIN)
        token = await self.start_session(user)
        await self._audit.append("auth.login", _actor(user), org_id=user.org_id)
        await self._s.commit()
        return await load_principal(self._s, user), token

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        row = await self._s.get(SessionRow, hash_token(token))
        if row is None:
            return
        user = await self._s.get(User, row.user_id)
        await self._s.delete(row)
        if user is not None:
            await self._audit.append("auth.logout", _actor(user), org_id=user.org_id)
        await self._s.commit()


def _actor(user: User) -> Actor:
    return Actor("user", user.id, user.name)
