"""Every cell of the roles → permissions table in docs/plans/2026-11-06-auth-roles-audit.md."""

import pytest
from aivee_api.auth.permissions import (
    PERMISSIONS,
    audit_scope,
    can_assign,
    has_permission,
    permissions_for,
)

# permission: (owner, manager, staff) — straight from the spec table.
TABLE: dict[str, tuple[bool, bool, bool]] = {
    "alerts.view": (True, True, True),
    "alerts.ack": (True, True, True),
    "staff.review": (True, True, False),
    "staff.enrol": (True, True, False),
    "rules.manage": (True, True, False),
    "devices.manage": (True, True, False),
    "users.manage": (True, True, False),
    "locations.manage": (True, False, False),
    "audit.view": (True, True, False),
    "audit.view.own": (False, False, True),
}
ROLES = ("owner", "manager", "staff")
CELLS = [(perm, role, row[i]) for perm, row in TABLE.items() for i, role in enumerate(ROLES)]


def test_the_table_covers_every_permission() -> None:
    assert set(TABLE) == set(PERMISSIONS)


@pytest.mark.parametrize(("permission", "role", "allowed"), CELLS)
def test_matrix_cell(permission: str, role: str, allowed: bool) -> None:
    assert has_permission(role, permission) is allowed  # type: ignore[arg-type]
    assert (permission in permissions_for(role)) is allowed  # type: ignore[arg-type]


def test_unknown_permission_is_never_granted() -> None:
    assert not has_permission("owner", "nuclear.launch")


@pytest.mark.parametrize(
    ("role", "scope"), [("owner", "org"), ("manager", "location"), ("staff", "own")]
)
def test_audit_scope(role: str, scope: str) -> None:
    assert audit_scope(role) == scope  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("actor", "target", "allowed"),
    [
        ("owner", "manager", True),
        ("owner", "staff", True),
        ("owner", "owner", False),
        ("manager", "staff", True),  # "✓ staff only, own location"
        ("manager", "manager", False),
        ("manager", "owner", False),
        ("staff", "staff", False),
        ("staff", "manager", False),
    ],
)
def test_users_manage_reach(actor: str, target: str, allowed: bool) -> None:
    assert can_assign(actor, target) is allowed  # type: ignore[arg-type]
