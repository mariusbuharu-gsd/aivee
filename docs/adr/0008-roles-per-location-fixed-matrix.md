# 8. Roles per location with a fixed permission matrix

Date: 2026-11-06 · Status: accepted · Decision log: D19, D21

## Context

An organization runs several locations (restaurants, terraces, events, shops). A waiter works at
one location and must see only its alerts; a manager runs one location; the owner sees all of them.
We have one day, and a configurable roles editor is a product of its own.

## Decision

- Tenancy: organization → locations → devices, cameras, zones, rules, events. A location is the
  existing `sites` row, and its id is the MQTT `<site>` segment.
- A user belongs to one organization. `is_owner` on the user gives the role `owner` at every location
  of the org; otherwise a `memberships` row gives `manager` or `staff` at one location.
- Three roles, one fixed matrix in code (`apps/api/src/aivee_api/auth/permissions.py`):

| Permission | owner | manager | staff |
|---|:-:|:-:|:-:|
| `alerts.view`, `alerts.ack` | ✓ | ✓ | ✓ |
| `staff.review`, `staff.enrol`, `rules.manage`, `devices.manage` | ✓ | ✓ | – |
| `users.manage` | ✓ (managers and staff) | ✓ (staff only) | – |
| `locations.manage` | ✓ | – | – |
| `audit.view` / `audit.view.own` | whole org | own location | own actions only |

- The API enforces it: `require(permission)` reads `?location_id=` (default: the caller's first
  location) and answers **404** when the location is not visible to the caller and **403** when the
  role lacks the permission. Routes that address a resource by id resolve its location first
  (`auth/scope.py`). The dashboard's `can(permission)` only hides buttons and routes.

## Consequences

- The matrix is small enough to unit-test cell by cell, and easy to explain to a client.
- Another org's data looks the same as data that does not exist (404, not 403).
- A new permission is a code change and a release, not a setting. Custom roles are out of scope.
- One user cannot belong to two organizations.
