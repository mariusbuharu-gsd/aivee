"""Romanian one-line summaries for audit entries (pure; shared by the API and ingest).

`summary_ro(kind, actor=..., target=..., **fields)` fills a fixed template per kind. Missing
fields render empty; an unknown kind falls back to "<actor>: <kind>" instead of raising,
so writing history can never break the action it records.
"""

from collections import defaultdict

ROLE_RO = {"owner": "proprietar", "manager": "manager", "staff": "angajat"}

TEMPLATES: dict[str, str] = {
    "auth.login": "{actor} s-a autentificat",
    "auth.login_failed": "Autentificare eșuată pentru {target}",
    "auth.logout": "{actor} s-a deconectat",
    "user.invited": "{actor} l-a invitat pe {target} ca {role} la {location}",
    "user.invite_revoked": "{actor} a anulat invitația pentru {target}",
    "user.joined": "{actor} s-a alăturat echipei ca {role} la {location}",
    "member.role_changed": "{actor} a schimbat rolul lui {target} din {from_role} în {to_role}",
    "member.removed": "{actor} i-a scos accesul lui {target} la {location}",
    "location.created": "{actor} a creat locația {target}",
    "location.updated": "{actor} a modificat locația {target}",
    "location.deleted": "{actor} a șters locația {target}",
    "camera.created": "{actor} a adăugat camera {target}",
    "camera.updated": "{actor} a modificat camera {target}",
    "camera.deleted": "{actor} a șters camera {target}",
    "zones.updated": "{actor} a modificat zonele camerei {target}",
    "rule.created": "{actor} a creat regula „{target}”",
    "rule.updated": "{actor} a modificat regula „{target}”",
    "rule.deleted": "{actor} a șters regula „{target}”",
    "staff.confirmed": "{actor} a confirmat o persoană din personal pe camera {target}",
    "staff.rejected": "{actor} a respins o sugestie de personal pe camera {target}",
    "staff.enrolled": "{actor} a adăugat {count} exemple la profilul {target}",
    "alert.opened": "Alertă nouă la {target}",
    "alert.acknowledged": "{actor} a preluat alerta de la {target}",
    "alert.arrived": "Personalul a ajuns la {target}",
    "alert.closed": "Alerta de la {target} s-a închis",
    "device.online": "Dispozitivul {actor} este online",
    "device.offline": "Dispozitivul {actor} s-a deconectat",
    "video.uploaded": "{actor} a încărcat clipul {target} pentru analiză",
    "video.analysed": "Analiza clipului {target} s-a încheiat: {count} alerte",
    "video.failed": "Analiza clipului {target} a eșuat: {error}",
}
KINDS: tuple[str, ...] = tuple(TEMPLATES)

_ROLE_FIELDS = ("role", "from_role", "to_role")


def role_ro(role: str) -> str:
    return ROLE_RO.get(role, role)


def summary_ro(kind: str, actor: str = "", target: str = "", **fields: str) -> str:
    template = TEMPLATES.get(kind)
    if template is None:
        return f"{actor}: {kind}"
    values: defaultdict[str, str] = defaultdict(str, fields, actor=actor, target=target)
    for name in _ROLE_FIELDS:
        if name in values:
            values[name] = role_ro(values[name])
    return template.format_map(values)
