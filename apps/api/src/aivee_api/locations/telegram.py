"""One-click "Conectează Telegram" for a location.

The API hands out a deep link `https://t.me/<bot>?startgroup=<code>` (or `?start=<code>`
for a private chat). The code is short, random and single use; only its sha256 is stored,
with the location and a 15-minute expiry. The bot's poller in ingest
(`aivee_ingest.telegram_link`) gets `/start <code>` from the chat and calls `consume_link`,
which saves the chat on the location. Neither the code nor its hash leaves the API again.
"""

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import User
from aivee_api.audit.repository import Actor, AuditRepository, Target
from aivee_api.auth.permissions import LOCATIONS_MANAGE
from aivee_api.auth.principal import NO_LOCATION, Principal
from aivee_api.auth.tokens import hash_token
from aivee_api.db.models import Site, TelegramLinkRow
from aivee_api.errors import NotFound, Unavailable

log = logging.getLogger(__name__)

LINK_TTL = timedelta(minutes=15)
CODE_BYTES = 12  # 16 url-safe characters, ~96 bits; Telegram allows up to 64
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
NO_BOT = "Botul Telegram nu este configurat pe server."
BOT_ACTOR = Actor("system", "telegram-bot", "Botul Telegram")


class BotUsername(Protocol):
    """The bot's @username (without the @), or None when it cannot be known."""

    async def username(self) -> str | None: ...


class StaticBotUsername:
    def __init__(self, name: str | None) -> None:
        self._name = name

    async def username(self) -> str | None:
        return self._name


class TelegramBotUsername:
    """TELEGRAM_BOT_USERNAME, else getMe once with TELEGRAM_BOT_TOKEN (cached on success).

    `client` is injectable so tests never reach api.telegram.org."""

    def __init__(
        self,
        configured: str | None,
        token: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._name = configured.lstrip("@") if configured else None
        self._token = token
        self._client = client

    async def username(self) -> str | None:
        if self._name or not self._token:
            return self._name
        client = self._client or httpx.AsyncClient(timeout=10)
        try:
            resp = await client.get(f"https://api.telegram.org/bot{self._token}/getMe")
            name = resp.json().get("result", {}).get("username") if resp.is_success else None
        except (httpx.HTTPError, ValueError) as e:
            # Never log the request URL: it carries the bot token.
            log.warning("Telegram getMe failed: %s", type(e).__name__)
            name = None
        finally:
            if self._client is None:
                await client.aclose()
        if isinstance(name, str) and name:
            self._name = name
        return self._name


class TelegramLinkOut(BaseModel):
    url: str
    """Add the bot to a group (`?startgroup=`)."""
    private_url: str
    """Or talk to it in a private chat (`?start=`)."""
    expires_at: datetime


class TelegramStatusOut(BaseModel):
    connected: bool
    chat_title: str | None = None


class TelegramLinkService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._s = session
        self._p = principal

    async def _site(self, location_id: str) -> Site:
        self._p.authorize(LOCATIONS_MANAGE, location_id)
        row = await self._s.get(Site, location_id)
        if row is None or row.org_id != self._p.org_id:
            raise NotFound(NO_LOCATION)
        return row

    async def create(self, location_id: str, bot: BotUsername | None) -> TelegramLinkOut:
        site = await self._site(location_id)
        username = await bot.username() if bot is not None else None
        if not username:
            raise Unavailable(NO_BOT)
        code = secrets.token_urlsafe(CODE_BYTES)
        expires = datetime.now(UTC) + LINK_TTL
        self._s.add(
            TelegramLinkRow(
                token_hash=hash_token(code),
                location_id=site.id,
                created_by_id=self._p.user_id,
                expires_at=expires,
            )
        )
        await self._s.commit()
        base = f"https://t.me/{username}"
        return TelegramLinkOut(
            url=f"{base}?startgroup={code}", private_url=f"{base}?start={code}", expires_at=expires
        )

    async def status(self, location_id: str) -> TelegramStatusOut:
        site = await self._site(location_id)
        if not site.telegram_chat_id:
            return TelegramStatusOut(connected=False)
        return TelegramStatusOut(connected=True, chat_title=site.telegram_chat_title)


LinkStatus = Literal["linked", "already_linked", "unknown", "expired", "used"]


@dataclass(frozen=True)
class LinkResult:
    status: LinkStatus
    location_name: str | None = None


async def consume_link(
    session: AsyncSession,
    code: str,
    chat_id: str,
    chat_title: str | None,
    now: datetime | None = None,
) -> LinkResult:
    """Use a code from `/start <code>` in chat `chat_id`; commits on success.

    "already_linked": the same chat sent the same code again (a redelivered update)."""
    if not CODE_RE.match(code):
        return LinkResult("unknown")
    now = now or datetime.now(UTC)
    row = await session.scalar(
        select(TelegramLinkRow)
        .where(TelegramLinkRow.token_hash == hash_token(code))
        .with_for_update()
    )
    if row is None:
        return LinkResult("unknown")
    site = await session.get(Site, row.location_id)
    if site is None:
        return LinkResult("unknown")
    name = site.name or site.id
    if row.used_at is not None:
        return LinkResult("already_linked" if row.chat_id == chat_id else "used", name)
    if row.expires_at <= now:
        return LinkResult("expired", name)
    before = {
        "telegram_chat_id": site.telegram_chat_id,
        "telegram_chat_title": site.telegram_chat_title,
    }
    site.telegram_chat_id = chat_id
    site.telegram_chat_title = chat_title
    row.used_at = now
    row.chat_id = chat_id
    creator = await session.get(User, row.created_by_id) if row.created_by_id else None
    actor = Actor("user", creator.id, creator.name) if creator else BOT_ACTOR
    await AuditRepository(session).append(
        "location.telegram_connected",
        actor,
        org_id=site.org_id,
        location_id=site.id,
        target=Target("location", site.id, name),
        before=before,
        after={"telegram_chat_id": chat_id, "telegram_chat_title": chat_title},
        chat=chat_title or chat_id,
    )
    await session.commit()
    return LinkResult("linked", name)
