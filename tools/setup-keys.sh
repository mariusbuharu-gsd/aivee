#!/usr/bin/env bash
# Asks for the API keys AiVee needs (input is hidden), writes them into the repo's .env,
# links that .env into every git worktree, and optionally stores the Anthropic key as a
# GitHub Actions secret. Values are never printed.
#
# Usage (in your own terminal):  make keys
set -euo pipefail

ROOT="$(cd "$(git -C "$(dirname "$0")" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
ENV_FILE="$ROOT/.env"

[[ -f "$ENV_FILE" ]] || cp "$ROOT/.env.example" "$ENV_FILE"
chmod 600 "$ENV_FILE"

set_var() { # name value -> replace or append NAME=value in .env without echoing it
  local name="$1" value="$2" tmp
  tmp="$(mktemp)"
  grep -v "^${name}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$name" "$value" >> "$tmp"
  cat "$tmp" > "$ENV_FILE" && rm -f "$tmp"
}

ask() { # name prompt
  local name="$1" prompt="$2" value current
  if grep -qE "^${name}=.+" "$ENV_FILE"; then current="set"; else current="empty"; fi
  read -r -s -p "$prompt [now: $current, Enter = keep]: " value; echo
  if [[ -n "$value" ]]; then set_var "$name" "$value"; echo "  ✓ $name saved"; else echo "  - $name kept"; fi
}

echo "AiVee keys → $ENV_FILE"
ask ANTHROPIC_API_KEY  "Anthropic API key (console.anthropic.com → API Keys)"
ask TELEGRAM_BOT_TOKEN "Telegram bot token (@BotFather → /newbot)"

# Web Push keys are generated, not pasted (kept if already set).
(cd "$ROOT" && uv run python tools/gen_vapid.py) || echo "  - VAPID keys skipped (run: make vapid)"

# The uploaded-clip runner's MQTT login: generated once, never printed. The broker reads it at
# start (infra/mosquitto/entrypoint.sh), so restart mosquitto after it is first set.
grep -qE '^MQTT_UPLOAD_USER=.+' "$ENV_FILE" || { set_var MQTT_UPLOAD_USER upload-01; echo "  ✓ MQTT_UPLOAD_USER set"; }
if ! grep -qE '^MQTT_UPLOAD_PASSWORD=.+' "$ENV_FILE"; then
  set_var MQTT_UPLOAD_PASSWORD "$(openssl rand -hex 24)"; echo "  ✓ MQTT_UPLOAD_PASSWORD generated (restart mosquitto)"
fi

# Link the single .env into every worktree so parallel sessions share one config.
while read -r wt; do
  [[ "$wt" == "$ROOT" ]] && continue
  ln -sfn "$ENV_FILE" "$wt/.env" && echo "  ↳ linked into ${wt#"$ROOT"/}"
done < <(git -C "$ROOT" worktree list --porcelain | awk '/^worktree /{print $2}')

read -r -p "Also store ANTHROPIC_API_KEY as a GitHub Actions secret? [y/N] " yn
if [[ "$yn" =~ ^[Yy]$ ]]; then
  grep -E '^ANTHROPIC_API_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '\n' \
    | gh secret set ANTHROPIC_API_KEY -R mariusbuharu-gsd/aivee && echo "  ✓ GitHub secret set"
fi

echo
echo "Next: add the bot to a Telegram group, write any message there, then run: make telegram-id"
