"""The fixed roles → permissions matrix (D21). Pure: no IO, unit-tested cell by cell.

A role is held *at a location*: `owner` at every location of the owner's organization,
`manager` / `staff` through a membership. Location scoping (which locations a user can see)
lives in `aivee_api.auth.deps`; this module only answers "may this role do that".
"""

from typing import Literal

Role = Literal["owner", "manager", "staff"]
MemberRole = Literal["manager", "staff"]
AuditScope = Literal["org", "location", "own"]

ALERTS_VIEW = "alerts.view"
ALERTS_ACK = "alerts.ack"
STAFF_REVIEW = "staff.review"
STAFF_ENROL = "staff.enrol"
RULES_MANAGE = "rules.manage"
DEVICES_MANAGE = "devices.manage"
USERS_MANAGE = "users.manage"
LOCATIONS_MANAGE = "locations.manage"
AUDIT_VIEW = "audit.view"
AUDIT_VIEW_OWN = "audit.view.own"

PERMISSIONS: tuple[str, ...] = (
    ALERTS_VIEW,
    ALERTS_ACK,
    STAFF_REVIEW,
    STAFF_ENROL,
    RULES_MANAGE,
    DEVICES_MANAGE,
    USERS_MANAGE,
    LOCATIONS_MANAGE,
    AUDIT_VIEW,
    AUDIT_VIEW_OWN,
)

_MANAGER = frozenset(
    {
        ALERTS_VIEW,
        ALERTS_ACK,
        STAFF_REVIEW,
        STAFF_ENROL,
        RULES_MANAGE,
        DEVICES_MANAGE,
        USERS_MANAGE,
        AUDIT_VIEW,
    }
)
MATRIX: dict[Role, frozenset[str]] = {
    "owner": _MANAGER | {LOCATIONS_MANAGE},
    "manager": _MANAGER,
    "staff": frozenset({ALERTS_VIEW, ALERTS_ACK, AUDIT_VIEW_OWN}),
}

_AUDIT_SCOPE: dict[Role, AuditScope] = {"owner": "org", "manager": "location", "staff": "own"}

# users.manage reach: which membership roles each role may grant, change or remove.
_ASSIGNABLE: dict[Role, frozenset[str]] = {
    "owner": frozenset({"manager", "staff"}),
    "manager": frozenset({"staff"}),
    "staff": frozenset(),
}


def permissions_for(role: Role) -> frozenset[str]:
    return MATRIX[role]


def has_permission(role: Role, permission: str) -> bool:
    return permission in MATRIX[role]


def audit_scope(role: Role) -> AuditScope:
    return _AUDIT_SCOPE[role]


def can_assign(actor: Role, target: Role) -> bool:
    """May `actor` grant, change or remove a membership whose role is (or becomes) `target`?"""
    return target in _ASSIGNABLE[actor]
