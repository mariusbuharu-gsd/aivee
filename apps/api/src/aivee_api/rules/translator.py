"""Romanian request → rule draft, behind the `RuleTranslator` port."""

import logging
from collections.abc import Sequence
from typing import Any, Literal, Protocol

import anthropic
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Condition
from pydantic import BaseModel, Field, ValidationError

from aivee_api.rules.prompt import INSTRUCTIONS, zones_block

log = logging.getLogger(__name__)

ErrorCode = Literal["clarify", "refusal", "max_tokens", "invalid", "rate_limited", "unavailable"]


MESSAGES_RO = {
    "invalid": "Nu am reușit să construiesc o regulă validă. Reformulați cererea.",
    "rate_limited": "Prea multe cereri în acest moment. Încercați din nou într-un minut.",
    "unavailable": "Serviciul de interpretare a cererilor nu răspunde. Încercați din nou.",
    "offline": "Nu mă pot conecta la serviciul de interpretare. Verificați rețeaua.",
    "refusal": "Această cerere nu poate fi transformată într-o regulă AiVee.",
    "max_tokens": "Cererea este prea lungă sau prea complexă. Scrieți-o mai pe scurt.",
}


class RuleDraft(BaseModel):
    """What the model fills; the service adds id, camera, prompt and action."""

    understood: bool = Field(description="false when the request must be clarified or refused")
    clarification_ro: str = Field(description='Romanian question or reason; "" if understood')
    name: str
    zone_tag: str
    all_of: list[Condition]
    cooldown_s: int
    explanation_ro: str


class TranslationError(Exception):
    """A request that did not become a rule. `message_ro` is shown to the owner as-is."""

    def __init__(self, code: ErrorCode, message_ro: str) -> None:
        super().__init__(f"{code}: {message_ro}")
        self.code = code
        self.message_ro = message_ro


class RuleTranslator(Protocol):
    async def translate(self, text: str, zones: Sequence[Zone]) -> RuleDraft: ...


class ClaudeRuleTranslator:
    def __init__(
        self,
        client: Any = None,  # anthropic.AsyncAnthropic or a test double with .messages.parse
        model: str = "claude-opus-5-5",
        max_tokens: int = 4000,
    ) -> None:
        self._client = client if client is not None else anthropic.AsyncAnthropic()
        self._model = model
        self._max_tokens = max_tokens

    async def translate(self, text: str, zones: Sequence[Zone]) -> RuleDraft:
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                output_config={"effort": "low"},
                system=[
                    {
                        "type": "text",
                        "text": INSTRUCTIONS,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": zones_block(zones)},
                ],
                messages=[{"role": "user", "content": text}],
                output_format=RuleDraft,
            )
        except ValidationError as e:
            log.warning("rule draft failed validation: %s", e.errors()[:3])
            raise TranslationError("invalid", MESSAGES_RO["invalid"]) from e
        except anthropic.RateLimitError as e:
            raise TranslationError("rate_limited", MESSAGES_RO["rate_limited"]) from e
        except anthropic.APIStatusError as e:
            log.warning("rule translation API error %s: %s", e.status_code, e.message)
            raise TranslationError("unavailable", MESSAGES_RO["unavailable"]) from e
        except anthropic.APIConnectionError as e:
            raise TranslationError("unavailable", MESSAGES_RO["offline"]) from e

        if response.stop_reason == "refusal":
            raise TranslationError("refusal", MESSAGES_RO["refusal"])
        if response.stop_reason == "max_tokens":
            raise TranslationError("max_tokens", MESSAGES_RO["max_tokens"])
        draft = response.parsed_output
        if not isinstance(draft, RuleDraft):
            raise TranslationError("invalid", MESSAGES_RO["invalid"])
        return draft
