"""Romanian summaries for every audit kind in the spec."""

import pytest
from aivee_api.audit.summaries import KINDS, role_ro, summary_ro

CASES = [
    ("auth.login", {"actor": "Ana"}, "Ana s-a autentificat"),
    (
        "auth.login_failed",
        {"actor": "Ana", "target": "ana@x.ro"},
        "Autentificare eșuată pentru ana@x.ro",
    ),
    ("auth.logout", {"actor": "Ana"}, "Ana s-a deconectat"),
    (
        "user.invited",
        {"actor": "Ana", "target": "ion@x.ro", "role": "staff", "location": "Terasa"},
        "Ana l-a invitat pe ion@x.ro ca angajat la Terasa",
    ),
    (
        "user.joined",
        {"actor": "Ion", "role": "staff", "location": "Terasa"},
        "Ion s-a alăturat echipei ca angajat la Terasa",
    ),
    (
        "member.role_changed",
        {"actor": "Ana", "target": "Ion", "from_role": "staff", "to_role": "manager"},
        "Ana a schimbat rolul lui Ion din angajat în manager",
    ),
    (
        "member.removed",
        {"actor": "Ana", "target": "Ion", "location": "Terasa"},
        "Ana i-a scos accesul lui Ion la Terasa",
    ),
    ("location.created", {"actor": "Ana", "target": "Terasa"}, "Ana a creat locația Terasa"),
    ("location.updated", {"actor": "Ana", "target": "Terasa"}, "Ana a modificat locația Terasa"),
    ("location.deleted", {"actor": "Ana", "target": "Terasa"}, "Ana a șters locația Terasa"),
    ("camera.created", {"actor": "Ana", "target": "Sala"}, "Ana a adăugat camera Sala"),
    ("camera.updated", {"actor": "Ana", "target": "Sala"}, "Ana a modificat camera Sala"),
    ("camera.deleted", {"actor": "Ana", "target": "Sala"}, "Ana a șters camera Sala"),
    ("zones.updated", {"actor": "Ana", "target": "Sala"}, "Ana a modificat zonele camerei Sala"),
    (
        "rule.created",
        {"actor": "Ana", "target": "Masă neservită"},
        "Ana a creat regula „Masă neservită”",
    ),
    (
        "rule.updated",
        {"actor": "Ana", "target": "Masă neservită"},
        "Ana a modificat regula „Masă neservită”",
    ),
    (
        "rule.deleted",
        {"actor": "Ana", "target": "Masă neservită"},
        "Ana a șters regula „Masă neservită”",
    ),
    (
        "staff.confirmed",
        {"actor": "Ana", "target": "Sala"},
        "Ana a confirmat o persoană din personal pe camera Sala",
    ),
    (
        "staff.rejected",
        {"actor": "Ana", "target": "Sala"},
        "Ana a respins o sugestie de personal pe camera Sala",
    ),
    (
        "staff.enrolled",
        {"actor": "Ana", "target": "Ospătar", "count": "3"},
        "Ana a adăugat 3 exemple la profilul Ospătar",
    ),
    ("alert.opened", {"actor": "edge-01", "target": "Masa 4"}, "Alertă nouă la Masa 4"),
    (
        "alert.acknowledged",
        {"actor": "Ana", "target": "Masa 4"},
        "Ana a preluat alerta de la Masa 4",
    ),
    ("alert.arrived", {"actor": "edge-01", "target": "Masa 4"}, "Personalul a ajuns la Masa 4"),
    ("alert.closed", {"actor": "edge-01", "target": "Masa 4"}, "Alerta de la Masa 4 s-a închis"),
    ("device.online", {"actor": "edge-01"}, "Dispozitivul edge-01 este online"),
    ("device.offline", {"actor": "edge-01"}, "Dispozitivul edge-01 s-a deconectat"),
]


@pytest.mark.parametrize(("kind", "fields", "expected"), CASES)
def test_summary(kind: str, fields: dict[str, str], expected: str) -> None:
    assert summary_ro(kind, **fields) == expected


def test_every_kind_has_a_case() -> None:
    assert {c[0] for c in CASES} == set(KINDS)


def test_unknown_kind_and_missing_fields_never_raise() -> None:
    assert summary_ro("weird.kind", actor="Ana") == "Ana: weird.kind"
    assert summary_ro("rule.created", actor="Ana") == "Ana a creat regula „”"


def test_role_names() -> None:
    assert (role_ro("owner"), role_ro("manager"), role_ro("staff")) == (
        "proprietar",
        "manager",
        "angajat",
    )
