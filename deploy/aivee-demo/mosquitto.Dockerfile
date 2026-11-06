# Server broker image: the stock Mosquitto with the repo's entrypoint and ACL baked in (a swarm
# stack has no bind mounts from the repo) and the server config with the WebSockets listener.
# Build from the repo root: docker build -f deploy/aivee-demo/mosquitto.Dockerfile .
FROM eclipse-mosquitto:2
COPY infra/mosquitto/entrypoint.sh /entrypoint.sh
COPY infra/mosquitto/acl /mosquitto/config/acl
COPY deploy/aivee-demo/mosquitto.conf /mosquitto/config/mosquitto.conf
RUN chown mosquitto:mosquitto /mosquitto/config/acl && chmod 0600 /mosquitto/config/acl
EXPOSE 1883 9001
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
