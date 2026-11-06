# AiVee — rules for every session

AiVee alerts restaurant staff when a guest waits too long. Rules are written in Romanian;
staff are recognised by appearance and behaviour (never by face); everything runs on the edge.

## Read first
- `docs/plans/2026-11-06-aivee-design.md` — what and why
- `docs/plans/2026-11-06-aivee-implementation.md` — tasks, owners, milestones

## Commands
- `make dev` — install the uv workspace (Python 3.12)
- `make test` — unit tests (fast, no Docker) · `make test-all` — plus integration (Docker)
- `make lint` — ruff + format check + mypy (strict on contracts and edge domain)
- `make up` / `make down` — Mosquitto, Postgres+pgvector (host port 5433), MediaMTX
- `make schema` — regenerate JSON Schema from `packages/contracts`

## Rules
- Stay inside your task's folders. `packages/contracts/` changes only when the task says so.
- TDD: failing test → minimal code → green → commit. `make test` and `make lint` must pass.
- `apps/edge/src/aivee_edge/domain/` is pure: no IO, no cv2/torch/ultralytics/mqtt imports.
  Everything external sits behind a `typing.Protocol` port, implemented in `adapters/`.
- Integration tests are marked `@pytest.mark.integration` and use testcontainers.
- Secrets live only in `.env` (gitignored). `.env.example` lists the names. Never print values.
- MQTT topics come from `aivee_contracts.topics.Topics`; never hand-write topic strings.
- Code, comments, docs and commits in English; UI copy in Romanian.

## Commits and PRs
- `type(scope): imperative summary` (feat, fix, docs, refactor, test, chore, ci) + a short why-body.
- **No AI attribution**: no `Co-Authored-By`, no session links, no mention of Claude or any model,
  in commits or PR descriptions.
- Small commits; one PR per task; squash merge after green CI.
- Branches: `feature/<slug>`, `fix/<slug>`, `docs/<slug>` from `develop`; PRs target `develop`.
- `develop` → `main` only through a release PR at a milestone (M1, M2, freeze). `main` is always demo-ready.
- Never push directly to `develop` or `main`.
