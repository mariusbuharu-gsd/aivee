"""A vision model's second opinion on an opened alert, before the staff are told.

The edge decides cheaply (YOLO, rules); this asks once per alert whether the image(s)
really show the rule's situation. `object_gone` sends the before and after images,
every other kind the single opened snapshot. The question is built from the rule's own
Romanian text.

Flow (VERIFY_ALERTS on, with an API key), run as a task so the MQTT handler never waits:
claim (status `pending`, at most once per alert) → wait for the snapshot(s) → verify with
a timeout → store status, summary, model and latency → notify:
- confirmed: notify with the model's Romanian summary;
- rejected: do not notify (a false alarm; the alert stays visible as "Neconfirmat" and
  closes when the edge closes it);
- unavailable (error, timeout, refusal, missing image): notify as a normal alert.
"""

import asyncio
import base64
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import anthropic
from aivee_api.alerts.repository import AlertRepository
from aivee_api.db.models import RuleRow
from aivee_contracts.events import AlertEvent, Verification, before_snapshot_id
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.config import IngestSettings
from aivee_ingest.notify import Notifier

log = logging.getLogger(__name__)

VerifyKind = Literal["object_gone", "snapshot"]

UNAVAILABLE = Verification(status="unavailable")


class AlertVerifier(Protocol):
    async def verify(
        self,
        rule_prompt_ro: str,
        zone_name: str,
        images: Sequence[bytes],
        kind: VerifyKind,
        objects: Sequence[str] = (),
    ) -> Verification:
        """`images` are blurred JPEGs: [before, after] for object_gone, else [snapshot]."""
        ...


@dataclass(frozen=True)
class VerifyContext:
    rule_prompt_ro: str
    zone_name: str


class VerificationStore(Protocol):
    async def claim(self, alert_id: str) -> bool:
        """Mark the alert pending; False if it was already verified (or is being)."""
        ...

    async def context(self, event: AlertEvent) -> VerifyContext: ...

    async def save(self, alert_id: str, verification: Verification) -> None: ...


# -- the question -------------------------------------------------------------------------

INSTRUCTIONS = """\
You check a restaurant monitoring alert against camera images. Faces are blurred on purpose;
never try to identify anyone. Answer the Romanian question that follows the images:
- The system already measured durations and timing ("de 1 minut", "după 2 min") from the
  video; one image cannot show time, so never reject because of time. Judge only whether the
  scene in the image is consistent with the rule (e.g. a guest is at the table and no member
  of staff is attending them).
- yes: true if the images show a scene consistent with the rule; false if they clearly show
  otherwise (e.g. nobody at the table, staff already serving, the object still there) or
  show nothing relevant.
- summary_ro: one short Romanian sentence that starts with the zone name, describing what
  you see, e.g. "Masa 1: a dispărut paharul de vin" or "Masa 2: clienții așteaptă".
- object_ro: the Romanian name of the object concerned, e.g. "pahar de vin"; "" if none.
"""


def question_ro(
    rule_prompt_ro: str, zone_name: str, kind: VerifyKind, objects: Sequence[str]
) -> str:
    rule = f"Regula: «{rule_prompt_ro}». Zona: {zone_name}."
    if kind == "object_gone":
        what = ", ".join(objects) or "obiect"
        return (
            f"{rule} Imaginea 1 este înainte, imaginea 2 după. A dispărut de pe masă, între "
            f"imaginea 1 și imaginea 2, un obiect de tipul: {what} (nume COCO)? "
            "Răspunde da/nu, descrie schimbarea într-o propoziție în română și dă numele "
            "obiectului în română."
        )
    return (
        f"{rule} Durata a fost deja măsurată de sistem. Ce se vede în imagine se potrivește "
        "cu situația din regulă? Răspunde da/nu și descrie scurt în română."
    )


class VerificationAnswer(BaseModel):
    yes: bool = Field(description="true if the images clearly show what the question asks")
    summary_ro: str
    object_ro: str = Field(description='Romanian name of the object; "" if none')


def _image(jpeg: bytes) -> dict[str, Any]:
    data = base64.b64encode(jpeg).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


class ClaudeAlertVerifier:
    def __init__(
        self,
        client: Any = None,  # anthropic.AsyncAnthropic or a test double with .messages.parse
        model: str = "claude-opus-5-5",
        max_tokens: int = 1000,
    ) -> None:
        self._client: Any = client if client is not None else anthropic.AsyncAnthropic()
        self.model = model
        self._max_tokens = max_tokens

    async def verify(
        self,
        rule_prompt_ro: str,
        zone_name: str,
        images: Sequence[bytes],
        kind: VerifyKind,
        objects: Sequence[str] = (),
    ) -> Verification:
        content: list[dict[str, Any]] = []
        for i, jpeg in enumerate(images, start=1):
            if len(images) > 1:
                content.append({"type": "text", "text": f"Imaginea {i}:"})
            content.append(_image(jpeg))
        content.append(
            {"type": "text", "text": question_ro(rule_prompt_ro, zone_name, kind, objects)}
        )
        try:
            response = await self._client.messages.parse(
                model=self.model,
                max_tokens=self._max_tokens,
                output_config={"effort": "low"},
                system=[
                    {
                        "type": "text",
                        "text": INSTRUCTIONS,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": content}],
                output_format=VerificationAnswer,
            )
        except ValidationError as e:
            log.warning("verification answer failed validation: %s", e.errors()[:3])
            return UNAVAILABLE
        except anthropic.APIStatusError as e:
            log.warning("verification API error %s: %s", e.status_code, e.message)
            return UNAVAILABLE
        except anthropic.APIConnectionError:
            log.warning("verification API unreachable")
            return UNAVAILABLE

        if response.stop_reason in ("refusal", "max_tokens"):
            log.warning("verification stopped: %s", response.stop_reason)
            return UNAVAILABLE
        answer = response.parsed_output
        if not isinstance(answer, VerificationAnswer):
            return UNAVAILABLE
        return Verification(
            status="confirmed" if answer.yes else "rejected",
            summary_ro=answer.summary_ro.strip(),
            object_ro=answer.object_ro.strip() or None,
            model=self.model,
        )


def build_verifier(settings: IngestSettings) -> AlertVerifier | None:
    """The real verifier when VERIFY_ALERTS is on and ANTHROPIC_API_KEY is set, else None."""
    if not settings.verify_alerts:
        log.info("verification: off (VERIFY_ALERTS)")
        return None
    if not settings.anthropic_api_key:
        log.info("verification: off (ANTHROPIC_API_KEY not set)")
        return None
    log.info("verification: %s, timeout %.0f s", settings.verify_model, settings.verify_timeout_s)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return ClaudeAlertVerifier(client, model=settings.verify_model)


# -- the flow -----------------------------------------------------------------------------


async def wait_for_file(file: Path, timeout_s: float) -> Path | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not file.is_file():
        if loop.time() >= deadline:
            log.warning("snapshot %s did not arrive in time", file.name)
            return None
        await asyncio.sleep(0.1)
    return file


class AlertVerification:
    def __init__(
        self,
        verifier: AlertVerifier,
        store: VerificationStore,
        notifier: Notifier,
        snapshot_dir: Path,
        timeout_s: float = 20.0,
        snapshot_wait_s: float = 2.0,
    ) -> None:
        self._verifier = verifier
        self._store = store
        self._notifier = notifier
        self._snapshots = snapshot_dir
        self._timeout_s = timeout_s
        self._snapshot_wait_s = snapshot_wait_s

    async def run(self, event: AlertEvent) -> Verification | None:
        """Verify, store and notify one opened alert; None if it was already claimed."""
        if not await self._store.claim(event.event_id):
            log.info("verification of %s already claimed", event.event_id)
            return None
        after = await self._file(event.event_id) if event.snapshot else None
        verification = await self._verify(event, after)
        await self._store.save(event.event_id, verification)
        log.info(
            "verification event_id=%s rule=%s status=%s model=%s latency_ms=%s summary=%r",
            event.event_id,
            event.rule_id,
            verification.status,
            verification.model,
            verification.latency_ms,
            verification.summary_ro,
        )
        if verification.status == "rejected":
            return verification
        notify = event
        if verification.status == "confirmed" and verification.summary_ro:
            notify = event.model_copy(update={"summary_ro": verification.summary_ro})
        try:
            await self._notifier.notify(notify, after)
        except Exception:
            log.exception("notifier failed for event %s", event.event_id)
        return verification

    async def _file(self, snapshot_id: str) -> Path | None:
        return await wait_for_file(self._snapshots / f"{snapshot_id}.jpg", self._snapshot_wait_s)

    async def _verify(self, event: AlertEvent, after: Path | None) -> Verification:
        if after is None:
            return UNAVAILABLE
        change = event.object_change
        kind: VerifyKind = "object_gone" if change is not None else "snapshot"
        images = [after.read_bytes()]
        if change is not None:
            before = (
                await self._file(before_snapshot_id(event.event_id))
                if change.before_snapshot
                else None
            )
            if before is None:
                return UNAVAILABLE  # nothing to compare the after image with
            images.insert(0, before.read_bytes())
        ctx = await self._store.context(event)
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._verifier.verify(
                    ctx.rule_prompt_ro,
                    ctx.zone_name,
                    images,
                    kind,
                    change.objects if change is not None else (),
                ),
                self._timeout_s,
            )
        except TimeoutError:
            log.warning(
                "verification of %s timed out after %.0f s", event.event_id, self._timeout_s
            )
            result = UNAVAILABLE
        except Exception:
            log.exception("verification of %s failed", event.event_id)
            result = UNAVAILABLE
        latency_ms = round((time.monotonic() - started) * 1000)
        return result.model_copy(update={"latency_ms": latency_ms})


class DbVerificationStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim(self, alert_id: str) -> bool:
        async with self._sessions() as s:
            claimed = await AlertRepository(s).claim_verification(alert_id, datetime.now(UTC))
            await s.commit()
        return claimed

    async def context(self, event: AlertEvent) -> VerifyContext:
        async with self._sessions() as s:
            rule = await s.get(RuleRow, event.rule_id)
            view = await AlertRepository(s).view(event.event_id)
        prompt = rule.prompt_ro if rule is not None and rule.prompt_ro else ""
        if not prompt and rule is not None:
            prompt = str(rule.rule.get("name", ""))
        return VerifyContext(prompt or event.summary_ro, view.zone_name if view else event.zone_id)

    async def save(self, alert_id: str, verification: Verification) -> None:
        async with self._sessions() as s:
            await AlertRepository(s).save_verification(alert_id, verification, datetime.now(UTC))
            await s.commit()
