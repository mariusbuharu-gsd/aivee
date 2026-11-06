#!/bin/sh
# Render the MediaMTX config from env at start so no secret is committed (same pattern as
# infra/mosquitto/entrypoint.sh). Base config: /mediamtx.base.yml (infra/mediamtx/mediamtx.yml).
#
# Publishing (the restaurant's connector or phone) needs STREAM_PUBLISH_USER/PASSWORD.
# Reading stays open as before: the dashboard live view and the cloud vision worker.
# Per-camera publish keys and read tokens issued by the API come later (roadmap P1.6).
set -eu
out=/tmp/mediamtx.yml
cp /mediamtx.base.yml "$out"

# MediaMTX accepts only these characters in credentials; fail early with a clear message.
# Generate a safe value with: openssl rand -hex 24
for v in "${STREAM_PUBLISH_USER:-}" "${STREAM_PUBLISH_PASSWORD:-}"; do
  if printf '%s' "$v" | grep -q '[^A-Za-z0-9!$()*+.;<=>^_,@#&[-]'; then
    echo "mediamtx: STREAM_PUBLISH_USER/PASSWORD may use only letters, digits and !\$()*+.;<=>[]^_-,@#&" >&2
    exit 64
  fi
done

# YAML single-quoted scalar (the allowed set contains no single quote).
q() { printf "'%s'" "$1"; }

{
  echo ""
  echo "authMethod: internal"
  echo "authInternalUsers:"
  echo "  - user: any"
  echo "    permissions:"
  echo "      - action: read"
  echo "      - action: playback"
  echo "  - user: any"
  echo "    ips: ['127.0.0.1', '::1']"
  echo "    permissions:"
  echo "      - action: api"
  echo "      - action: metrics"
  if [ -n "${STREAM_PUBLISH_USER:-}" ] && [ -n "${STREAM_PUBLISH_PASSWORD:-}" ]; then
    echo "  - user: $(q "$STREAM_PUBLISH_USER")"
    echo "    pass: $(q "$STREAM_PUBLISH_PASSWORD")"
    echo "    permissions:"
    echo "      - action: publish"
  fi
} >> "$out"

if [ -z "${STREAM_PUBLISH_USER:-}" ] || [ -z "${STREAM_PUBLISH_PASSWORD:-}" ]; then
  echo "mediamtx: STREAM_PUBLISH_USER/STREAM_PUBLISH_PASSWORD not set; publishing is disabled" >&2
fi

exec /mediamtx "$out"
