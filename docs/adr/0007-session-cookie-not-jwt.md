# 7. Opaque sessions in an HttpOnly cookie, not JWT

Date: 2026-11-06 · Status: accepted · Decision log: D20

## Context

AiVee needs real accounts (owner, manager, staff) for a dashboard that runs in the browser and
on waiters' phones. There is no identity provider on site, and one API process serves both REST
and the `/ws/events` WebSocket. A logout or a removed staff member must take effect at once.

## Decision

- Passwords are hashed with argon2 (`argon2-cffi`), minimum 8 characters.
- Login creates an opaque random token (32 bytes, `secrets.token_urlsafe`). Only its sha256 is
  stored, in `sessions`, with a sliding expiry (`SESSION_TTL_HOURS`, default 12 h; the new expiry
  is written back at most once a minute).
- The token travels only in the cookie `aivee_session`: `HttpOnly; SameSite=Lax; Path=/`, plus
  `Secure` when `COOKIE_SECURE=true`. The dashboard calls the API with `credentials: "include"`;
  CORS allows credentials only for the explicit `CORS_ORIGINS`.
- `/ws/events` authenticates with the same cookie on the handshake (closed with 1008 otherwise).
- Failed logins are limited to 10 per email per 15 minutes (429 with a Romanian message).

Code: `apps/api/src/aivee_api/auth/` (`tokens.py`, `deps.py`, `service.py`, `ratelimit.py`).

## Consequences

- Script in the page cannot read the token (nothing in `localStorage`), so an XSS cannot steal it.
- Logout and member removal are immediate: the row is deleted and the next request gets 401.
  A JWT would stay valid until it expires, or need a revocation list, which is a session table again.
- Every request reads one row by primary key. Fine for one API per deployment.
- The dashboard and the API must be same-site for the cookie (`localhost:5173` → `localhost:8000` is).
  A phone needs both on the same host name, and HTTPS for push.
- The login rate limit lives in memory: a restart forgets it, and several API processes would
  each count on their own.
