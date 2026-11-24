"""Per-camera push keys for `POST /api/ingest/frames/{camera_id}` (S6).

A key is a random URL-safe string shown once; the camera row keeps only its sha256 (hex).
The connector sends it as `Authorization: Bearer <key>`. A camera with a key refuses the
shared STREAM_PUBLISH_USER/PASSWORD, so a leaked shared credential cannot reach it.
"""

import hashlib
import hmac
import secrets


def new_key() -> str:
    return secrets.token_urlsafe(32)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def key_matches(given: str, stored_hash: str | None) -> bool:
    """Constant-time check of a presented key against the camera's stored hash."""
    if not stored_hash or not given:
        return False
    return hmac.compare_digest(key_hash(given), stored_hash)


def bearer(header: str | None) -> str | None:
    """The key of an `Authorization: Bearer <key>` header, else None."""
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None
