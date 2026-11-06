# 6. An LLM turns a Romanian request into a rule, confirmed by a human

Date: 2026-11-06 · Status: accepted · Decision log: D5

## Context

Owners are not technical. They describe what they want in Romanian ("Anunță ospătarul dacă
la o masă nu a venit nimeni de 1 minut"). The edge needs a precise, typed `Rule`: zone tag,
conditions (present / absent / count / pose / objects), durations, cooldown, action.

## Decision

The API calls Claude (`claude-opus-5-5`, effort low) with `messages.parse` and a `RuleDraft`
structured output (`apps/api/.../rules/translator.py`). Fixed instructions come first and the
camera's zones last, so the prompt prefix is cache-friendly.

- The model may answer with a clarifying question instead of a rule (vague, impossible or
  out-of-scope requests such as face recognition or fire detection).
- The result is a **draft**. The dashboard shows "Ce am înțeles" and the owner confirms,
  edits or discards it. Only a confirmed rule is saved and published to the edge.
- Refusals, `max_tokens` and SDK errors map to Romanian error messages.

## Consequences

- Eval `evals/nl_to_rule` (20 Romanian requests, including no-diacritics and refusals):
  20/20, median 2.4 s, max 4.0 s (`make eval`, results in `evals/nl_to_rule/results.md`).
- The model never acts on its own: it only proposes a rule the schema validates.
- Rule creation needs internet; running rules do not (they execute on the edge).
- Each request is one paid API call; rules are created rarely, so the cost is small.
