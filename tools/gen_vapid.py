"""Generate a VAPID key pair for Web Push and write it into the repo's .env.

Writes VAPID_PUBLIC_KEY (base64url uncompressed P-256 point, the browser's
`applicationServerKey`), VAPID_PRIVATE_KEY (base64url raw scalar) and, when missing,
VAPID_SUBJECT. Existing keys are kept unless --force is given: rotating them invalidates
every phone's subscription. Never prints the values.

Usage: make vapid  (or: uv run python tools/gen_vapid.py [--force])
"""

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ENV = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_SUBJECT = "mailto:aivee@example.com"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64url(public), b64url(private)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip()
    return values


def write_vars(path: Path, updates: dict[str, str]) -> None:
    lines = [ln for ln in path.read_text().splitlines() if ln.partition("=")[0] not in updates]
    lines += [f"{name}={value}" for name, value in updates.items()]
    path.write_text("\n".join(lines) + "\n")


def main(argv: list[str]) -> int:
    env = ENV
    if not env.exists():
        print(f"{env} not found; copy .env.example first", file=sys.stderr)
        return 1
    current = read_env(env)
    if current.get("VAPID_PRIVATE_KEY") and "--force" not in argv:
        print("VAPID keys already set in .env (use --force to rotate them)")
        return 0
    public, private = generate()
    updates = {"VAPID_PUBLIC_KEY": public, "VAPID_PRIVATE_KEY": private}
    if not current.get("VAPID_SUBJECT"):
        updates["VAPID_SUBJECT"] = DEFAULT_SUBJECT
    write_vars(env, updates)
    print(f"wrote {', '.join(updates)} to {env}; restart api and ingest to use them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
