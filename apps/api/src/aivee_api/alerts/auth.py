"""Alert permissions over the logged-in user (aivee_api.auth).

`Access.locations` is the set of location ids the user holds the permission in (an owner:
every location of the organization). The alert services return 404 for anything outside
it. A `?location_id=` the user can see but lacks the permission at is 403; one the user
cannot see is 404 (the services also check it).
"""

from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Query

from aivee_api.auth.deps import CurrentUser as LoggedIn
from aivee_api.auth.permissions import ALERTS_ACK, ALERTS_VIEW
from aivee_api.auth.principal import FORBIDDEN, Principal
from aivee_api.errors import Forbidden


class CurrentUser(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


@dataclass(frozen=True)
class AlertUser:
    id: str
    name: str


@dataclass(frozen=True)
class Access:
    user: CurrentUser
    locations: frozenset[str] | None = None

    def allows(self, location_id: str | None) -> bool:
        return self.locations is None or location_id in self.locations


def access_for(principal: Principal, permission: str, location_id: str | None) -> Access:
    """403 when the user holds `permission` nowhere, or not at a visible `location_id`."""
    if location_id is not None and principal.role_at(location_id) is not None:
        principal.authorize(permission, location_id)
    locations = frozenset(principal.locations_with(permission))
    if not locations and principal.locations:
        raise Forbidden(FORBIDDEN)
    return Access(AlertUser(principal.user_id, principal.name), locations)


LocationQuery = Annotated[str | None, Query(max_length=64)]


async def require_ack(principal: LoggedIn, location_id: LocationQuery = None) -> Access:
    """Permission `alerts.ack`."""
    return access_for(principal, ALERTS_ACK, location_id)


async def require_view(principal: LoggedIn, location_id: LocationQuery = None) -> Access:
    """Permission `alerts.view`."""
    return access_for(principal, ALERTS_VIEW, location_id)


AckAccess = Annotated[Access, Depends(require_ack)]
ViewAccess = Annotated[Access, Depends(require_view)]
