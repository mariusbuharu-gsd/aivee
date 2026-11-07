"""Find the Telegram group the bot was added to and save its id as TELEGRAM_CHAT_ID.

Reads TELEGRAM_BOT_TOKEN from the repo's .env, calls getUpdates, picks the most recent
group/supergroup chat and writes TELEGRAM_CHAT_ID back into .env. Never prints the token.
Then sends a test message to that chat.

Usage: make telegram-id

Prefer "Conectează Telegram" in the dashboard (Locații). While ingest runs its link poller
(TELEGRAM_POLL, default on), this script's getUpdates conflicts with it and finds nothing.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def write_var(name: str, value: str) -> None:
    lines = [ln for ln in ENV.read_text().splitlines() if not ln.startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    ENV.write_text("\n".join(lines) + "\n")


def call(token: str, method: str, **params: str) -> dict[str, object]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(url, data=data, timeout=15) as resp:
        result: dict[str, object] = json.load(resp)
        return result


def main() -> int:
    token = read_env().get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN is empty in .env — run `make secrets` first.")
        return 1
    updates = call(token, "getUpdates").get("result", [])
    chats = [
        u[k]["chat"]
        for u in updates  # type: ignore[union-attr]
        for k in ("message", "my_chat_member", "channel_post")
        if k in u and u[k]["chat"]["type"] in ("group", "supergroup", "channel")
    ]
    if not chats:
        print("No group found. Add the bot to a group, write a message there, then retry.")
        return 1
    chat = chats[-1]
    write_var("TELEGRAM_CHAT_ID", str(chat["id"]))
    print(f"✓ TELEGRAM_CHAT_ID saved for group “{chat.get('title', '?')}”")
    call(token, "sendMessage", chat_id=str(chat["id"]), text="AiVee: alertele vor ajunge aici. ✅")
    print("✓ test message sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
