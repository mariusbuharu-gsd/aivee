"""How an alert ends, in Romanian: the line that replaces its buttons, and the follow-ups.

    ✅ Rezolvat · un angajat a ajuns după 25 s · preluată de Ana
    ⚪ Închisă · clientul a plecat
    👋 Clientul a plecat de la Masa 1 fără să fie servit (a așteptat 3 min 10 s)
    ⏰ Încă neservit: Masa 1, de 4 min

Pure: no IO. "Clientul" only makes sense for a waiting guest; an object or visual rule
(a missing glass, a fire) gets neutral wording.
"""

from collections.abc import Sequence
from datetime import datetime

from aivee_api.alerts.domain import duration_ro
from aivee_api.alerts.schemas import AlertView
from aivee_contracts.rules import Condition

_GUEST_KINDS = frozenset({"present", "absent", "count", "pose"})
_THING_KINDS = frozenset({"objects_unattended", "object_gone", "object_present", "visual"})


def is_guest_rule(conditions: Sequence[Condition]) -> bool:
    """A rule about people waiting (the default when the rule is unknown)."""
    kinds = {c.kind for c in conditions}
    if not kinds:
        return True
    return bool(kinds & _GUEST_KINDS) and not kinds & _THING_KINDS


def _waited(view: AlertView) -> str:
    return duration_ro(view.wait_s) if view.wait_s is not None else ""


def resolved_line(view: AlertView) -> str:
    after = f" după {_waited(view)}" if view.wait_s is not None else ""
    taken = f" · preluată de {view.acknowledged_by}" if view.acknowledged_by else ""
    return f"✅ Rezolvat · un angajat a ajuns{after}{taken}"


def closed_line(*, guest: bool) -> str:
    return "⚪ Închisă · clientul a plecat" if guest else "⚪ Închisă · situația s-a încheiat"


def left_ro(view: AlertView, *, guest: bool) -> str:
    waited = _waited(view)
    if guest:
        tail = f" (a așteptat {waited})" if waited else ""
        return f"👋 Clientul a plecat de la {view.zone_name} fără să fie servit{tail}"
    tail = f" după {waited}" if waited else ""
    return f"⚪ Alerta de la {view.zone_name} s-a închis singură{tail}"


def reminder_ro(view: AlertView, now: datetime, *, guest: bool) -> str:
    minutes = max(1, int((now - view.opened_at).total_seconds() // 60))
    what = "neservit" if guest else "nerezolvat"
    return f"⏰ Încă {what}: {view.zone_name}, de {minutes} min"
