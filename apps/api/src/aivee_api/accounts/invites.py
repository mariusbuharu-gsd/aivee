"""Invites by link (D20): a manager or owner invites an email to a location with a role.

The link carries an opaque token (only its sha256 is stored), is valid 7 days and works once.
Pending invites (not accepted, not revoked, not expired) can be listed and revoked; a revoked
link answers 410. Neither the token nor its hash ever leaves the API.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import Invite, Membership, Organization, User
from aivee_api.audit.repository import Actor, AuditRepository, Target
from aivee_api.auth.deps import Access, CurrentUser, require, set_session_cookie
from aivee_api.auth.passwords import hash_password
from aivee_api.auth.permissions import USERS_MANAGE, MemberRole, can_assign
from aivee_api.auth.principal import FORBIDDEN, Principal, load_principal
from aivee_api.auth.ratelimit import LoginRateLimiter
from aivee_api.auth.schemas import Me, me_out
from aivee_api.auth.service import (
    AuthService,
    check_password,
    clean_email,
    clean_name,
    email_taken,
    new_id,
)
from aivee_api.auth.tokens import hash_token, new_token
from aivee_api.db.models import Site
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.errors import Conflict, Forbidden, Gone, NotFound
from aivee_api.settings import ApiSettings

NO_INVITE = "Invitația nu există sau a expirat."
EMAIL_TAKEN = "Există deja un cont cu acest email."
REVOKED = "Invitația a fost anulată."
NOT_FOUND = "Invitația nu există."
ALREADY_ACCEPTED = "Invitația a fost deja acceptată și nu mai poate fi anulată."


class InviteIn(BaseModel):
    location_id: str = Field(max_length=64)
    role: MemberRole
    email: str = Field(max_length=320)


class InviteOut(BaseModel):
    invite_url: str
    expires_at: datetime


class InviteInfo(BaseModel):
    org_name: str
    location_name: str
    role: Literal["manager", "staff"]
    email: str


class InviteCreator(BaseModel):
    id: str
    name: str


class PendingInvite(BaseModel):
    id: str
    email: str
    role: Literal["manager", "staff"]
    location_id: str
    created_by: InviteCreator | None = Field(
        description="Who sent it; null when that account was deleted"
    )
    created_at: datetime
    expires_at: datetime


class AcceptIn(BaseModel):
    name: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class InviteService:
    def __init__(self, session: AsyncSession, settings: ApiSettings) -> None:
        self._s = session
        self._settings = settings
        self._audit = AuditRepository(session)

    async def create(self, p: Principal, data: InviteIn) -> InviteOut:
        actor_role = p.authorize(USERS_MANAGE, data.location_id)
        if not can_assign(actor_role, data.role):
            raise Forbidden(FORBIDDEN)
        email = clean_email(data.email)
        if await email_taken(self._s, email):
            raise Conflict(EMAIL_TAKEN)
        token = new_token()
        expires = datetime.now(UTC) + timedelta(days=self._settings.invite_ttl_days)
        self._s.add(
            Invite(
                id=new_id("inv"),
                token_hash=hash_token(token),
                org_id=p.org_id,
                location_id=data.location_id,
                role=data.role,
                email=email,
                invited_by=p.user_id,
                expires_at=expires,
            )
        )
        loc = p.location(data.location_id)
        await self._audit.append(
            "user.invited",
            p.actor,
            org_id=p.org_id,
            location_id=data.location_id,
            target=Target("email", email[:128], email),
            after={"email": email, "role": data.role, "expires_at": expires.isoformat()},
            role=data.role,
            location=loc.name if loc else data.location_id,
        )
        await self._s.commit()
        return InviteOut(
            invite_url=f"{self._settings.invite_base_url}/invitatie/{token}", expires_at=expires
        )

    async def _valid(self, token: str, *, lock: bool = False) -> Invite:
        stmt = select(Invite).where(Invite.token_hash == hash_token(token))
        invite = await self._s.scalar(stmt.with_for_update() if lock else stmt)
        if invite is None or invite.accepted_at is not None:
            raise NotFound(NO_INVITE)
        if invite.revoked_at is not None:
            raise Gone(REVOKED)
        if invite.expires_at <= datetime.now(UTC):
            raise NotFound(NO_INVITE)
        return invite

    async def pending(self, access: Access) -> list[PendingInvite]:
        """Newest first; a manager sees only the roles they may grant (staff)."""
        roles = [r for r in ("manager", "staff") if can_assign(access.role, r)]
        rows = await self._s.execute(
            select(Invite, User.name)
            .outerjoin(User, User.id == Invite.invited_by)
            .where(
                Invite.org_id == access.principal.org_id,
                Invite.location_id == access.location_id,
                Invite.role.in_(roles),
                Invite.accepted_at.is_(None),
                Invite.revoked_at.is_(None),
                Invite.expires_at > datetime.now(UTC),
            )
            .order_by(Invite.created_at.desc(), Invite.id.desc())
        )
        return [
            PendingInvite(
                id=inv.id,
                email=inv.email,
                role=inv.role,  # type: ignore[arg-type]
                location_id=inv.location_id,
                created_by=InviteCreator(id=inv.invited_by, name=name or "")
                if inv.invited_by
                else None,
                created_at=inv.created_at,
                expires_at=inv.expires_at,
            )
            for inv, name in rows
        ]

    async def revoke(self, p: Principal, invite_id: str) -> None:
        """Idempotent: revoking a revoked invite changes (and audits) nothing. Another
        organization's or location's invite does not exist for the caller (404)."""
        invite = await self._s.scalar(
            select(Invite).where(Invite.id == invite_id).with_for_update()
        )
        if invite is None or invite.org_id != p.org_id or p.role_at(invite.location_id) is None:
            raise NotFound(NOT_FOUND)
        actor_role = p.authorize(USERS_MANAGE, invite.location_id)
        if not can_assign(actor_role, invite.role):  # type: ignore[arg-type]
            raise Forbidden(FORBIDDEN)
        if invite.revoked_at is not None:
            return
        if invite.accepted_at is not None:
            raise Conflict(ALREADY_ACCEPTED)
        invite.revoked_at = datetime.now(UTC)
        await self._audit.append(
            "user.invite_revoked",
            p.actor,
            org_id=p.org_id,
            location_id=invite.location_id,
            target=Target("email", invite.email[:128], invite.email),
            before={
                "email": invite.email,
                "role": invite.role,
                "expires_at": invite.expires_at.isoformat(),
            },
        )
        await self._s.commit()

    async def info(self, token: str) -> InviteInfo:
        invite = await self._valid(token)
        org = await self._s.get(Organization, invite.org_id)
        site = await self._s.get(Site, invite.location_id)
        return InviteInfo(
            org_name=org.name if org else "",
            location_name=site.name if site else invite.location_id,
            role=invite.role,  # type: ignore[arg-type]
            email=invite.email,
        )

    async def accept(
        self, token: str, data: AcceptIn, limiter: LoginRateLimiter
    ) -> tuple[Principal, str]:
        name = clean_name(data.name)
        check_password(data.password)
        invite = await self._valid(token, lock=True)
        if await email_taken(self._s, invite.email):
            raise Conflict(EMAIL_TAKEN)
        user = User(
            id=new_id("u"),
            org_id=invite.org_id,
            email=invite.email,
            name=name,
            password_hash=hash_password(data.password),
            is_owner=False,
        )
        self._s.add(user)
        await self._s.flush()
        self._s.add(Membership(user_id=user.id, location_id=invite.location_id, role=invite.role))
        invite.accepted_at = datetime.now(UTC)
        site = await self._s.get(Site, invite.location_id)
        await self._audit.append(
            "user.joined",
            Actor("user", user.id, user.name),
            org_id=invite.org_id,
            location_id=invite.location_id,
            target=Target("user", user.id, user.name),
            after={"role": invite.role},
            role=invite.role,
            location=site.name if site else invite.location_id,
        )
        session_token = await AuthService(self._s, self._settings, limiter).start_session(user)
        await self._s.commit()
        return await load_principal(self._s, user), session_token


router = APIRouter(prefix="/api/invites", tags=["invites"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_invite(
    data: InviteIn, s: SessionDep, svc: ServicesDep, p: CurrentUser
) -> InviteOut:
    return await InviteService(s, svc.settings).create(p, data)


@router.get("")
async def list_invites(
    s: SessionDep,
    svc: ServicesDep,
    access: Annotated[Access, Depends(require(USERS_MANAGE))],
) -> list[PendingInvite]:
    """Pending invites of `?location_id=` (default: the caller's first location)."""
    return await InviteService(s, svc.settings).pending(access)


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser) -> None:
    await InviteService(s, svc.settings).revoke(p, invite_id)


@router.get("/{token}")
async def get_invite(token: str, s: SessionDep, svc: ServicesDep) -> InviteInfo:
    """Public: what the invite link is for, before the person sets a password."""
    return await InviteService(s, svc.settings).info(token)


@router.post("/{token}/accept")
async def accept_invite(
    token: str, data: AcceptIn, response: Response, s: SessionDep, svc: ServicesDep
) -> Me:
    principal, session_token = await InviteService(s, svc.settings).accept(
        token, data, svc.login_limiter
    )
    set_session_cookie(response, session_token, svc.settings)
    return me_out(principal)
