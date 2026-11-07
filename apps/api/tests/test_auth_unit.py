"""Password hashing, opaque session tokens and the login rate limit (no DB)."""

from datetime import UTC, datetime, timedelta

import pytest
from aivee_api.auth.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordTooShort,
    hash_password,
    needs_rehash,
    verify_password,
)
from aivee_api.auth.ratelimit import LoginRateLimiter
from aivee_api.auth.tokens import hash_token, new_token, should_extend

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def test_hash_is_argon2_and_verifies() -> None:
    h = hash_password("parola-buna")
    assert h.startswith("$argon2id$")
    assert "parola-buna" not in h
    assert verify_password(h, "parola-buna")
    assert not verify_password(h, "parola-rea")
    assert not needs_rehash(h)


def test_same_password_hashes_differently() -> None:
    assert hash_password("parola-buna") != hash_password("parola-buna")


def test_verify_never_raises_on_garbage() -> None:
    assert not verify_password("not-a-hash", "whatever1")
    assert not verify_password("", "whatever1")


def test_password_minimum_length() -> None:
    assert MIN_PASSWORD_LENGTH == 8
    with pytest.raises(PasswordTooShort):
        hash_password("1234567")
    hash_password("12345678")


def test_token_is_32_random_bytes_urlsafe() -> None:
    a, b = new_token(), new_token()
    assert a != b
    assert len(a) == 43  # 32 bytes, urlsafe base64 without padding
    assert set(a) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_token_hash_is_sha256_hex_and_stable() -> None:
    t = new_token()
    assert hash_token(t) == hash_token(t)
    assert len(hash_token(t)) == 64 and hash_token(t) != t
    assert hash_token(t) != hash_token(new_token())


def test_sliding_expiry_extends_only_after_a_minute() -> None:
    ttl = timedelta(hours=12)
    assert not should_extend(T0 + ttl, T0 + timedelta(seconds=30), ttl)
    assert should_extend(T0 + ttl, T0 + timedelta(minutes=2), ttl)


def test_rate_limit_allows_ten_failures_per_window() -> None:
    now = [T0]
    rl = LoginRateLimiter(max_failures=10, window=timedelta(minutes=15), clock=lambda: now[0])
    for _ in range(10):
        assert not rl.blocked("ana@x.ro")
        rl.failed("ana@x.ro")
    assert rl.blocked("ana@x.ro")
    assert rl.blocked("ANA@x.ro ")  # emails are normalised
    assert not rl.blocked("ion@x.ro")  # per email


def test_rate_limit_window_slides() -> None:
    now = [T0]
    rl = LoginRateLimiter(max_failures=10, window=timedelta(minutes=15), clock=lambda: now[0])
    for i in range(10):
        now[0] = T0 + timedelta(minutes=i)
        rl.failed("ana@x.ro")
    assert rl.blocked("ana@x.ro")
    now[0] = T0 + timedelta(minutes=15, seconds=1)  # the first failure left the window
    assert not rl.blocked("ana@x.ro")
    rl.failed("ana@x.ro")
    assert rl.blocked("ana@x.ro")
