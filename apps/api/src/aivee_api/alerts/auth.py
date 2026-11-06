"""Seam to the auth stream (A). Until it lands, everyone is a demo user who sees everything.

Swap at merge — either replace the bodies of `require_ack` / `require_view`, or override
them in `create_app`:

    app.dependency_overrides[require_ack] = <dep returning Access for "alerts.ack">
    app.dependency_overrides[require_view] = <dep returning Access for "alerts.view">

`Access.locations` is the set of location ids the user holds the permission in (None =
every location, e.g. an owner). The alert services return 404 for anything outside it.
"""

import re
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Header


class CurrentUser(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


@dataclass(frozen=True)
class DemoUser:
    id: str
    name: str


DEMO_USER = DemoUser(id="demo", name="Demo")


@dataclass(frozen=True)
class Access:
    user: CurrentUser
    locations: frozenset[str] | None = None

    def allows(self, location_id: str | None) -> bool:
        return self.locations is None or location_id in self.locations


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "demo"


async def demo_user(
    x_demo_user: Annotated[str | None, Header(description="Demo: acting user's name")] = None,
) -> CurrentUser:
    """`X-Demo-User: Ana` acts as Ana (id `demo-ana`); without it, the demo user."""
    name = (x_demo_user or "").strip()
    return DemoUser(id=f"demo-{_slug(name)}", name=name) if name else DEMO_USER


async def require_ack(user: Annotated[CurrentUser, Depends(demo_user)]) -> Access:
    """Permission `alerts.ack`."""
    return Access(user)


async def require_view(user: Annotated[CurrentUser, Depends(demo_user)]) -> Access:
    """Permission `alerts.view`."""
    return Access(user)


AckAccess = Annotated[Access, Depends(require_ack)]
ViewAccess = Annotated[Access, Depends(require_view)]
