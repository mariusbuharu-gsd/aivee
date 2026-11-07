# 3. Postgres 17 with pgvector

Date: 2026-11-06 · Status: accepted · Decision log: D7

## Context

We store cameras, zones, rules, alert events, staff suggestions and staff appearance
profiles (CLIP embeddings). Several ingest workers write concurrently; the API reads.

## Decision

One Postgres 17 database with the pgvector extension, schema managed by Alembic migrations
(a `migrate` service runs them on `make up`). No SQLite, no separate vector store.

## Consequences

- Concurrent writers from several ingest workers are safe; unique keys reject duplicate events.
- Staff profile embeddings and nearest-profile queries live next to the relational data.
- The database is the source of truth; the API rebuilds retained MQTT state from it (ADR 2).
- Integration tests run against a real Postgres + pgvector through testcontainers.
- One more service to run than SQLite, which Docker Compose hides.
