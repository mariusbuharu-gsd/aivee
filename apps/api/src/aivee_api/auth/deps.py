"""FastAPI dependencies: `CurrentUser` (401 without a valid session) and `require(permission)`.

    access: Annotated[Access, Depends(require(RULES_MANAGE))]

reads `?location_id=` (default: the caller's first location) and returns the caller's role
there: 404 when the location is not visible to the caller, 403 when the role lacks the
permission. Routes addressing a resource by id (camera, rule, …) use `CurrentUser` and call
`principal.authorize(permission, <the resource's location>)` themselves.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Query, Request, Response

from aivee_api.auth.permissions import Role
from aivee_api.auth.principal import Principal, principal_for_token
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.errors import Unauthenticated
from aivee_api.settings import ApiSettings

COOKIE = "aivee_session"
NOT_LOGGED_IN = "Trebuie să vă autentificați."


def set_session_cookie(response: Response, token: str, settings: ApiSettings) -> None:
    """Max-Age equals the session TTL and is re-sent whenever the sliding expiry moves."""
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(timedelta(hours=settings.session_ttl_hours).total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response, settings: ApiSettings) -> None:
    response.delete_cookie(
        COOKIE, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure
    )


async def current_principal(
    request: Request, response: Response, s: SessionDep, svc: ServicesDep
) -> Principal:
    token = request.cookies.get(COOKIE)
    ttl = timedelta(hours=svc.settings.session_ttl_hours)
    found = await principal_for_token(s, token, ttl)
    if found is None:
        raise Unauthenticated(NOT_LOGGED_IN)
    if found.extended_until is not None and token:
        set_session_cookie(response, token, svc.settings)
    return found.principal


CurrentUser = Annotated[Principal, Depends(current_principal)]


@dataclass(frozen=True)
class Access:
    principal: Principal
    location_id: str
    role: Role


def require(permission: str) -> Callable[..., Awaitable[Access]]:
    async def dependency(
        principal: CurrentUser,
        location_id: Annotated[str | None, Query(max_length=64)] = None,
    ) -> Access:
        loc = location_id or principal.default_location()
        return Access(principal, loc, principal.authorize(permission, loc))

    dependency.__name__ = f"require_{permission.replace('.', '_')}"
    return dependency
