"""Romanian request → rule eval: `make eval` (needs ANTHROPIC_API_KEY; costs a few cents).

Runs every case in cases.yaml through the real translator plus the API's draft checks,
prints a per-case table and the score, and writes results.md next to this file, plus
drafts.json (each case's raw model output, the source of the translator's parse tests).
"""

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from aivee_api.rules.service import draft_to_rule
from aivee_api.rules.translator import ClaudeRuleTranslator, TranslationError
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Condition, Rule

HERE = Path(__file__).resolve().parent
REFUSED = {"clarify", "refusal"}
CONCURRENCY = 5


@dataclass
class Outcome:
    case_id: str
    passed: bool
    seconds: float
    got: str
    why: str = ""
    draft: dict[str, Any] | None = None


def _match(value: Any, expected: Any) -> bool:
    return value in expected if isinstance(expected, list) else value == expected


def _condition_ok(cond: Condition, exp: dict[str, Any]) -> bool:
    if cond.kind != exp["kind"]:
        return False
    for key in ("role", "min_duration_s", "min_count", "pose"):
        if key in exp and not _match(getattr(cond, key), exp[key]):
            return False
    return set(exp.get("objects_include", [])) <= set(cond.objects)


def check(rule: Rule, expect: dict[str, Any]) -> str:
    """'' when the rule satisfies `expect`, otherwise the reason it does not."""
    if expect.get("refuse"):
        return "expected a refusal/clarification, got a rule"
    if not _match(rule.zone_tag, expect["zone_tag"]):
        return f"zone_tag {rule.zone_tag!r} != {expect['zone_tag']!r}"
    if "cooldown_s" in expect and rule.cooldown_s != expect["cooldown_s"]:
        return f"cooldown_s {rule.cooldown_s} != {expect['cooldown_s']}"
    wanted = expect["conditions"]
    if len(rule.all_of) != len(wanted):
        return f"{len(rule.all_of)} conditions, expected {len(wanted)}"
    remaining = list(rule.all_of)
    for exp in wanted:
        hit = next((c for c in remaining if _condition_ok(c, exp)), None)
        if hit is None:
            return f"no condition matching {exp}"
        remaining.remove(hit)
    return ""


def describe(rule: Rule) -> str:
    parts = []
    for c in rule.all_of:
        bits: list[str] = [c.kind, c.role]
        if c.min_duration_s:
            bits.append(f"{c.min_duration_s}s")
        if c.kind == "count":
            bits.append(f"≥{c.min_count}")
        if c.pose:
            bits.append(c.pose)
        if c.objects:
            bits.append(f"{len(c.objects)} obj" if len(c.objects) > 2 else "/".join(c.objects))
        if c.kind == "visual":
            bits.append(f"+{len(c.positive)}/-{len(c.negative)} t{c.threshold} {c.crop}")
        parts.append(" ".join(bits))
    return f"{rule.zone_tag}: " + " ∧ ".join(parts) + f" (cd {rule.cooldown_s}s)"


async def run_case(
    translator: ClaudeRuleTranslator, case: dict[str, Any], zones: list[Zone], gate: Any
) -> Outcome:
    async with gate:
        start = time.monotonic()
        raw: dict[str, Any] | None = None
        try:
            draft = await translator.translate(case["text"], zones)
            raw = draft.model_dump(mode="json")
            rule = draft_to_rule(draft, "cam1", case["text"], zones)
        except TranslationError as e:
            secs = time.monotonic() - start
            got = f"{e.code}: {e.message_ro}"
            if case["expect"].get("refuse") and e.code in REFUSED:
                return Outcome(case["id"], True, secs, got, draft=raw)
            return Outcome(case["id"], False, secs, got, "expected a rule", draft=raw)
        secs = time.monotonic() - start
        why = check(rule, case["expect"])
        return Outcome(case["id"], not why, secs, describe(rule), why, draft=raw)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def report(outcomes: list[Outcome], cases: list[dict[str, Any]], model: str) -> str:
    score = sum(o.passed for o in outcomes)
    secs = sorted(o.seconds for o in outcomes)
    median = secs[len(secs) // 2] if secs else 0.0
    lines = [
        "# Eval: Romanian request → rule",
        "",
        f"- date: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        f"- model: `{model}` (effort low)",
        f"- **score: {score}/{len(outcomes)}**",
        f"- latency: median {median:.1f}s, max {max(secs, default=0):.1f}s",
        "",
        "| # | case | ok | s | request | got | why |",
        "|---|---|---|---|---|---|---|",
    ]
    texts = {c["id"]: c["text"] for c in cases}
    for i, o in enumerate(outcomes, 1):
        lines.append(
            f"| {i} | {o.case_id} | {'✅' if o.passed else '❌'} | {o.seconds:.1f} | "
            f"{_cell(texts[o.case_id])} | {_cell(o.got)} | {_cell(o.why)} |"
        )
    return "\n".join(lines) + "\n"


async def main() -> int:
    spec = yaml.safe_load((HERE / "cases.yaml").read_text())
    zones = [Zone.model_validate(z) for z in spec["zones"]]
    cases: list[dict[str, Any]] = spec["cases"]
    translator = ClaudeRuleTranslator()
    gate = asyncio.Semaphore(CONCURRENCY)
    outcomes = await asyncio.gather(*(run_case(translator, c, zones, gate) for c in cases))

    width = max(len(c["id"]) for c in cases)
    for o in outcomes:
        mark = "PASS" if o.passed else "FAIL"
        print(f"{mark}  {o.case_id:<{width}}  {o.seconds:4.1f}s  {o.got}")
        if o.why:
            print(f"      {'':<{width}}  → {o.why}")
    score = sum(o.passed for o in outcomes)
    print(f"\nscore: {score}/{len(outcomes)}")
    (HERE / "results.md").write_text(report(list(outcomes), cases, "claude-opus-5-5"))
    drafts = {o.case_id: o.draft for o in outcomes}
    (HERE / "drafts.json").write_text(json.dumps(drafts, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {HERE / 'results.md'}")
    return 0 if score == len(outcomes) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
