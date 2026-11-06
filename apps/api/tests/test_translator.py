from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from aivee_api.rules.prompt import INSTRUCTIONS
from aivee_api.rules.service import draft_to_rule
from aivee_api.rules.translator import ClaudeRuleTranslator, RuleDraft, TranslationError
from aivee_contracts.geometry import Zone
from pydantic import ValidationError

ZONES = [
    Zone(id="t1", name="Masa 1", tag="table", polygon=[(0, 0), (0.2, 0), (0.2, 0.2)]),
    Zone(id="e1", name="Intrare", tag="entrance", polygon=[(0.5, 0), (0.7, 0), (0.7, 0.2)]),
]


class FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def _client(response: Any = None, error: Exception | None = None) -> Any:
    return SimpleNamespace(messages=FakeMessages(response, error))


def _response(stop_reason: str = "end_turn", parsed: Any = None) -> Any:
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


async def test_success_returns_the_draft_and_sends_a_cache_friendly_request(
    draft_factory: Any,
) -> None:
    draft = draft_factory()
    client = _client(_response(parsed=draft))

    result = await ClaudeRuleTranslator(client).translate("Anunță ospătarul...", ZONES)

    assert result == draft
    kw = client.messages.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["max_tokens"] == 4000
    assert kw["output_config"] == {"effort": "low"}
    assert kw["output_format"] is RuleDraft
    assert kw["messages"] == [{"role": "user", "content": "Anunță ospătarul..."}]
    fixed, volatile = kw["system"]
    assert fixed["text"] == INSTRUCTIONS and "cache_control" in fixed
    assert '"table"' in volatile["text"] and "Masa 1" in volatile["text"]
    assert "Intrare" not in INSTRUCTIONS  # zones only in the volatile block


async def test_patterns_and_roles_are_in_the_fixed_prompt() -> None:
    for needle in (
        "raised_hand",
        "objects_unattended",
        "object_gone",
        "wine glass",
        "guest",
        "staff",
        "any",
    ):
        assert needle in INSTRUCTIONS


@pytest.mark.parametrize(
    ("stop_reason", "code"), [("refusal", "refusal"), ("max_tokens", "max_tokens")]
)
async def test_stop_reasons_become_romanian_errors(stop_reason: str, code: str) -> None:
    client = _client(_response(stop_reason=stop_reason))
    with pytest.raises(TranslationError) as e:
        await ClaudeRuleTranslator(client).translate("x", ZONES)
    assert e.value.code == code
    assert e.value.message_ro


async def test_validation_error_from_parse_is_invalid() -> None:
    try:
        RuleDraft.model_validate({"understood": True})
    except ValidationError as err:
        error = err
    client = _client(error=error)
    with pytest.raises(TranslationError) as e:
        await ClaudeRuleTranslator(client).translate("x", ZONES)
    assert e.value.code == "invalid"


async def test_missing_parsed_output_is_invalid() -> None:
    with pytest.raises(TranslationError) as e:
        await ClaudeRuleTranslator(_client(_response(parsed=None))).translate("x", ZONES)
    assert e.value.code == "invalid"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            anthropic.RateLimitError(
                "slow down", response=httpx.Response(429, request=_request()), body=None
            ),
            "rate_limited",
        ),
        (
            anthropic.InternalServerError(
                "boom", response=httpx.Response(500, request=_request()), body=None
            ),
            "unavailable",
        ),
        (anthropic.APIConnectionError(request=_request()), "unavailable"),
    ],
)
async def test_sdk_errors_are_mapped(error: Exception, code: str) -> None:
    with pytest.raises(TranslationError) as e:
        await ClaudeRuleTranslator(_client(error=error)).translate("x", ZONES)
    assert e.value.code == code


def test_draft_to_rule_fills_the_rest(draft_factory: Any) -> None:
    rule = draft_to_rule(draft_factory(), "cam1", "cerere", ZONES)
    assert rule.camera_id == "cam1"
    assert rule.prompt_ro == "cerere"
    assert rule.action.type == "telegram"
    assert rule.id.startswith("r-")
    assert [c.kind for c in rule.all_of] == ["present", "absent"]


def test_not_understood_asks_for_clarification(draft_factory: Any) -> None:
    draft = draft_factory(understood=False, clarification_ro="Ce masă?", all_of=[])
    with pytest.raises(TranslationError) as e:
        draft_to_rule(draft, "cam1", "x", ZONES)
    assert (e.value.code, e.value.message_ro) == ("clarify", "Ce masă?")


def test_unknown_zone_tag_asks_to_draw_it(draft_factory: Any) -> None:
    with pytest.raises(TranslationError) as e:
        draft_to_rule(draft_factory(zone_tag="bar"), "cam1", "x", ZONES)
    assert e.value.code == "clarify" and "bar" in e.value.message_ro


def test_empty_conditions_are_invalid(draft_factory: Any) -> None:
    with pytest.raises(TranslationError) as e:
        draft_to_rule(draft_factory(all_of=[]), "cam1", "x", ZONES)
    assert e.value.code == "invalid"
