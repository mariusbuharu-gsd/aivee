#!/bin/sh
# Build the password file from env at start so no secret is committed.
set -e
f=/mosquitto/config/passwd
: > "$f"
mosquitto_passwd -b "$f" "$MQTT_API_USER" "$MQTT_API_PASSWORD"
mosquitto_passwd -b "$f" "$MQTT_INGEST_USER" "$MQTT_INGEST_PASSWORD"
mosquitto_passwd -b "$f" "$MQTT_EDGE_USER" "$MQTT_EDGE_PASSWORD"
# Optional: the device that analyses uploaded clips (ACL: the same %u pattern as an edge).
if [ -n "$MQTT_UPLOAD_USER" ] && [ -n "$MQTT_UPLOAD_PASSWORD" ]; then
  mosquitto_passwd -b "$f" "$MQTT_UPLOAD_USER" "$MQTT_UPLOAD_PASSWORD"
fi
# Optional: more edge devices, as space-separated `user:password` pairs (each user is also its
# device id; the ACL's %u patterns apply). Passwords must not contain spaces or colons
# (openssl rand -hex 24). The server stack uses it for edge-coleg-1..3.
for pair in ${MQTT_EXTRA_DEVICES:-}; do
  u="${pair%%:*}"; p="${pair#*:}"
  if [ -z "$u" ] || [ -z "$p" ] || [ "$u" = "$pair" ]; then
    echo "mosquitto: skipping a malformed MQTT_EXTRA_DEVICES entry (want user:password)" >&2
    continue
  fi
  mosquitto_passwd -b "$f" "$u" "$p"
done
chown mosquitto:mosquitto "$f"
chmod 0700 "$f"
exec mosquitto -c /mosquitto/config/mosquitto.conf
