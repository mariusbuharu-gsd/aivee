"""Alert permissions over the logged-in user and the live scope of folded alerts (no DB)."""

from datetime import UTC, datetime

import pytest
from aivee_api.alerts.auth import AlertUser, access_for
from aivee_api.alerts.schemas import AlertView, AlertViewMessage
from aivee_api.auth.permissions import ALERTS_ACK, ALERTS_VIEW
from aivee_api.auth.principal import LocationAccess, Principal
from aivee_api.errors import Forbidden, NotFound
from aivee_api.events.scope import LiveScope


def _principal(*roles: tuple[str, str], owner: bool = False) -> Principal:
    return Principal(
        user_id="u-ana",
        name="Ana",
        email="ana@a.ro",
        org_id="org-a",
        org_name="A",
        is_owner=owner,
        locations=tuple(LocationAccess(loc, loc, "other", role) for loc, role in roles),  # type: ignore[arg-type]
    )


def test_access_is_the_users_locations_holding_the_permission() -> None:
    access = access_for(_principal(("demo", "staff"), ("other", "manager")), ALERTS_ACK, None)
    assert access.user == AlertUser("u-ana", "Ana")
    assert access.locations == frozenset({"demo", "other"})
    assert access.allows("demo") and not access.allows("far") and not access.allows(None)


def test_an_owner_gets_the_org_locations_never_everything() -> None:
    access = access_for(_principal(("demo", "owner"), owner=True), ALERTS_VIEW, None)
    assert access.locations == frozenset({"demo"})


def test_an_unknown_location_is_left_to_the_service_404() -> None:
    access = access_for(_principal(("demo", "staff")), ALERTS_VIEW, "far")
    assert not access.allows("far")


def test_a_visible_location_without_the_permission_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    import aivee_api.auth.principal as principal

    monkeypatch.setattr(principal, "has_permission", lambda role, perm: perm != ALERTS_ACK)
    p = _principal(("demo", "staff"))
    with pytest.raises(Forbidden):
        access_for(p, ALERTS_ACK, "demo")
    with pytest.raises(Forbidden):
        access_for(p, ALERTS_ACK, None)


def test_a_user_without_locations_sees_nothing() -> None:
    assert access_for(_principal(), ALERTS_VIEW, None).locations == frozenset()
    with pytest.raises(NotFound):
        _principal().default_location()


def _view(location_id: str | None) -> AlertViewMessage:
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    return AlertViewMessage(
        data=AlertView(
            event_id="e1",
            rule_id="r1",
            location_id=location_id,
            camera_id="cam1",
            zone_id="t1",
            zone_name="Masa 1",
            summary_ro="Masa 1",
            opened_at=now,
            state="opened",
            at=now,
        )
    )


def test_live_scope_lets_folded_alerts_of_the_users_locations_through() -> None:
    scope = LiveScope(alert_locations={"demo"}, suggestion_locations=())
    assert scope.alert_locations == frozenset({"demo"})
    assert scope.allows(_view("demo"))
    assert not scope.allows(_view("other"))
    assert not scope.allows(_view(None))
