# AiVee docs — start here

Every new session (human or tool) reads this page first, then the handbook for its area.

| Need | Read |
|---|---|
| What we build and why | [plans/2026-11-06-aivee-design.md](plans/2026-11-06-aivee-design.md) |
| Tasks, streams, milestones | [plans/2026-11-06-aivee-implementation.md](plans/2026-11-06-aivee-implementation.md) |
| **Decisions already taken** (don't reopen without a reason) | [decisions.md](decisions.md) |
| Dashboard, PWA, presentation site, design | [handbook/frontend.md](handbook/frontend.md) |
| Edge, MQTT, API, ingest, Postgres | [handbook/backend.md](handbook/backend.md) |
| Architecture diagrams, alert and rule flows, scalability | [architecture.md](architecture.md) |
| Architecture decision records | [ADR 1 edge CPU inference](adr/0001-edge-first-cpu-inference.md) · [ADR 2 MQTT](adr/0002-mqtt-acl-lwt-retained-shared.md) · [ADR 3 Postgres + pgvector](adr/0003-postgres-pgvector.md) · [ADR 4 contracts](adr/0004-contracts-single-source-of-truth.md) · [ADR 5 staff without faces](adr/0005-staff-by-appearance-and-behaviour.md) · [ADR 6 request → rule](adr/0006-llm-request-to-rule.md) |
| Ideas and open questions (not scheduled) | [backlog/ideas.md](backlog/ideas.md) |
| Logo, mark, icon, favicon | [brand/](brand/) |
| Session rules (TDD, commits, no AI attribution) | [../CLAUDE.md](../CLAUDE.md) |

## Starting a parallel session in its own worktree

```bash
cd ~/1.Development/Projects-2025/aivee
git fetch && git worktree add ../aivee-<topic> -b feature/<topic> origin/develop
cd ../aivee-<topic>
ln -s ../aivee/.env .env        # one shared .env, never committed
ln -s ../aivee/models models    # edge model weights (only if you run the edge)
make dev                        # Python workspace; for the dashboard: cd apps/dashboard && npm ci
```

Work, commit small, then open a PR into `develop`. `main` only moves at milestones.
Remove the worktree when merged: `git worktree remove ../aivee-<topic>`.

## Who owns what (avoid stepping on each other)

| Area | Folders |
|---|---|
| Contracts (shared types, topics) | `packages/contracts/` — change only in a dedicated PR, then `make schema` and `npm run contracts` |
| Edge | `apps/edge/`, `tools/fake_edge.py`, `tools/bench_edge.py` |
| Backend | `apps/api/`, `apps/ingest/`, `infra/`, `docker-compose.yml`, `evals/` |
| Dashboard | `apps/dashboard/` |
| Site and pitch | `apps/site/`, `docs/brand/`, slides |
