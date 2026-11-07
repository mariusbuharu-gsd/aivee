# 9. An append-only audit log, enforced in the database

Date: 2026-11-06 · Status: accepted · Decision log: D22

## Context

Owners want to know who changed a rule, who took an alert and how fast, and when a device went
offline. A history that the application can edit proves nothing: a bug or a compromised API could
rewrite it.

## Decision

- One table, `audit_log` (migration `0003_auth_tenancy`): actor (user / device / system), kind
  (`auth.login`, `rule.updated`, `alert.acknowledged`, `device.offline`, ...), target, Romanian
  `summary_ro`, and `before` / `after` JSONB for configuration changes.
- Append-only twice over:
  - `REVOKE UPDATE, DELETE, TRUNCATE ON audit_log` from `PUBLIC` and from the role that runs the
    migration, which is the API's role;
  - triggers `BEFORE UPDATE OR DELETE` (per row) and `BEFORE TRUNCATE` that raise an exception,
    because a table owner or a superuser ignores privileges.
- The repository exposes only `append` and `query`. The API writes user actions; ingest writes
  `alert.*` (actor = device) in the same transaction as the event row, and `device.online|offline`.
- `GET /api/audit` is newest first, cursor-paginated (`before`), and scoped by role: owner → whole
  organization, manager → own location, staff → own actions.

## Consequences

- Neither the application nor anyone with its credentials can alter history without a migration
  that drops the trigger, and that migration shows up in review.
- The audit row is written in the same transaction as the change: no change without its entry.
- The table only grows. Retention (monthly partitions, archiving) is future work.
- `DROP TABLE` is not blocked; it needs DDL rights, which the running app should not have in production.
