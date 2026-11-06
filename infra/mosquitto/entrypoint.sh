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
chown mosquitto:mosquitto "$f"
chmod 0700 "$f"
exec mosquitto -c /mosquitto/config/mosquitto.conf
