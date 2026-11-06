"""The Telegram alert message: what happened, what it means, where — pure, no IO.

    🔴 <b>Masa 1 așteaptă de 1 min</b>
    Nu a venit nimeni la client.

    📍 Terasa demo · Sala principală · 16:56

The branch follows the rule's most specific condition, in the edge's own order
(`aivee_edge.domain.engine.summary_ro`): object_gone, pose, objects_unattended, count,
absent, present. Without a known rule the edge's `summary_ro` is the headline. A confirmed
vision check replaces the canned explanation with the model's summary.
"""

import html
import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from aivee_api.alerts.domain import duration_ro
from aivee_contracts.events import AlertEvent, Verification
from aivee_contracts.rules import Condition

from aivee_ingest.notify import LOCAL_TZ  # locations carry no time zone of their own

ACK_PREFIX = "ack:"
"""`callback_data` of the "Preiau ✋" button: `ack:<alert id>` (Telegram allows 64 bytes)."""
ACK_BUTTON = "Preiau ✋"
OPEN_BUTTON = "Vezi în aplicație"
ALERTS_PATH = "/alerte"


@dataclass(frozen=True)
class AlertContext:
    """Everything the message needs, names already resolved (ids only as a fallback)."""

    event: AlertEvent
    zone_name: str
    location_name: str
    camera_name: str
    conditions: Sequence[Condition] = ()
    verification: Verification | None = None


def basic_context(event: AlertEvent) -> AlertContext:
    """No database at hand: ids stand in for the names, the summary for the rule."""
    zone = event.summary_ro.partition(":")[0].strip() if ":" in event.summary_ro else ""
    return AlertContext(event, zone or event.zone_id, "", event.camera_id)


def _first_word_article(noun: str) -> str:
    """ "un pahar de vin", "o sticlă": Romanian feminine nouns mostly end in -ă, -a, -e."""
    if re.match(r"^(un|o|niște|unul|una)\s", noun, re.IGNORECASE):
        return noun
    first = noun.split()[0] if noun.split() else noun
    return f"o {noun}" if first.lower().endswith(("ă", "a", "e")) else f"un {noun}"


def _gone_what(ctx: AlertContext) -> str:
    v = ctx.verification
    if v is not None and v.status == "confirmed" and v.object_ro:
        return _first_word_article(v.object_ro.strip())
    # The edge already names the object in Romanian: "Masa 1: a dispărut paharul de vin".
    tail = ctx.event.summary_ro.partition("a dispărut")[2].strip()
    return tail or "un obiect"


def _count(ctx: AlertContext, c: Condition) -> int:
    found = re.search(r"(\d+)\s+persoane", ctx.event.summary_ro)
    return int(found.group(1)) if found else c.min_count


def headline_explanation(ctx: AlertContext) -> tuple[str, str]:
    """(headline, explanation) in Romanian, without ids."""
    zone = ctx.zone_name
    by_kind = {c.kind: c for c in ctx.conditions}
    headline: str
    explanation: str
    if ctx.event.object_change is not None or "object_gone" in by_kind:
        headline, explanation = f"{zone}: a dispărut {_gone_what(ctx)}", "Verifică masa."
    elif "pose" in by_kind:
        headline, explanation = f"{zone}: un client cheamă", "Un client a ridicat mâna."
    elif c := by_kind.get("objects_unattended"):
        headline = f"{zone} e nedebarasată de {duration_ro(c.min_duration_s)}"
        explanation = "Clienții au plecat, masa n-a fost strânsă."
    elif c := by_kind.get("count"):
        headline = f"{zone}: {_count(ctx, c)} persoane așteaptă"
        explanation = "S-a strâns lume. Trimite pe cineva să ajute."
    elif c := by_kind.get("absent"):
        headline = f"{zone} așteaptă de {duration_ro(c.min_duration_s)}"
        explanation = "Nu a venit nimeni la client."
    elif c := by_kind.get("present"):
        headline = f"{zone} e ocupată de {duration_ro(c.min_duration_s)}"
        explanation = "Vezi dacă clienții au nevoie de ceva."
    else:
        headline, explanation = ctx.event.summary_ro or zone, ""
    v = ctx.verification
    if v is not None and v.status == "confirmed" and v.summary_ro.strip():
        explanation = v.summary_ro.strip()
    if explanation == headline:
        explanation = ""
    return headline, explanation


def local_time(at: datetime) -> str:
    return at.astimezone(LOCAL_TZ).strftime("%H:%M")


def place_line(ctx: AlertContext) -> str:
    """ "Terasa demo · Sala principală · 16:56" (empty names are left out)."""
    parts = [ctx.location_name, ctx.camera_name, local_time(ctx.event.at)]
    return " · ".join(p for p in parts if p)


def ack_line(name: str, at: datetime) -> str:
    return f"✋ Preluată de {name} · {local_time(at)}"


def render(
    ctx: AlertContext, *, prefix: str = "", extra: Sequence[str] = (), as_html: bool = True
) -> str:
    """The message (HTML for `parse_mode=HTML`, or plain text for the fallback send).
    `extra` lines go at the end, e.g. the "✋ Preluată de Ana" line after an ack."""
    esc = html.escape if as_html else (lambda s: s)
    headline, explanation = headline_explanation(ctx)
    top = f"<b>{esc(headline)}</b>" if as_html else headline
    first = " ".join(p for p in (esc(prefix), "🔴", top) if p)
    lines = [first]
    if explanation:
        lines.append(esc(explanation))
    lines += ["", f"📍 {esc(place_line(ctx))}"]
    if extra:
        lines += [esc(x) for x in extra]
    return "\n".join(lines)


def public_https_url(url: str | None) -> str | None:
    """The URL without a trailing slash if Telegram will accept it in a button: https and a
    public host name (no localhost, no private or loopback IP, a dot in the name)."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ""
    except ValueError:
        return None
    if parts.scheme != "https" or not host or host == "localhost" or host.endswith(".local"):
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            return None
    else:
        if not ip.is_global:
            return None
    return url.strip().rstrip("/")


def ack_data(alert_id: str) -> str | None:
    data = f"{ACK_PREFIX}{alert_id}"
    return data if len(data.encode()) <= 64 else None


def alert_ref(callback_data: str | None) -> str | None:
    """The alert id in a "Preiau ✋" button's data, else None."""
    if not callback_data or not callback_data.startswith(ACK_PREFIX):
        return None
    return callback_data.removeprefix(ACK_PREFIX) or None


def keyboard(
    alert_id: str, dashboard_url: str | None, *, with_ack: bool = True
) -> dict[str, Any] | None:
    """`reply_markup`: [Preiau ✋] [Vezi în aplicație]; None when there is no button."""
    row: list[dict[str, str]] = []
    data = ack_data(alert_id) if with_ack else None
    if data is not None:
        row.append({"text": ACK_BUTTON, "callback_data": data})
    base = public_https_url(dashboard_url)
    if base is not None:
        row.append({"text": OPEN_BUTTON, "url": f"{base}{ALERTS_PATH}"})
    return {"inline_keyboard": [row]} if row else None
