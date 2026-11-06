"""Opaque tokens for sessions and invites. Only the sha256 of a token is ever stored."""

import hashlib
import secrets
from datetime import datetime, timedelta

TOKEN_BYTES = 32
# Extend a sliding session at most once a minute, not on every request.
EXTEND_EVERY = timedelta(minutes=1)


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def should_extend(expires_at: datetime, now: datetime, ttl: timedelta) -> bool:
    """True when the sliding expiry (`now + ttl`) is worth writing back."""
    return now + ttl - expires_at >= EXTEND_EVERY
