#!/usr/bin/env bash
# Run a one-off task from the api image next to the aivee-demo stack, wait for it, print its
# log and remove it. Runs on the manager, from ~/aivee-demo (reads aivee.env there).
#
#   TAG=<sha8> ./run-once.sh migrate     # Alembic upgrade head (before or after a deploy)
#   TAG=<sha8> ./run-once.sh seed        # demo org + owner@/manager@/staff@aivee.demo
#   TAG=<sha8> ./run-once.sh -- python -m some.module --flag   # anything else
#
# A one-off swarm service rather than a migrate-on-start: one task, run once, with a clear
# exit code, and never two replicas migrating at the same time.
set -euo pipefail
cd "$(dirname "$0")"

: "${TAG:?set TAG to the api image tag}"
STACK="${STACK:-aivee-demo}"
IMAGE="docker-hub.gsd.com.ro/aivee/api:$TAG"

case "${1:-}" in
  migrate) name=migrate; cmd=(python -m aivee_api.db.migrate upgrade) ;;
  # DEMO_PASSWORD comes from aivee.env, so the seed never writes or prints a password.
  seed) name=seed; cmd=(python -m aivee_api.accounts.seed) ;;
  --) shift; name=task; cmd=("$@") ;;
  *) echo "usage: TAG=<sha8> $0 migrate|seed|-- <command...>" >&2; exit 2 ;;
esac

svc="${STACK}_once-${name}"
docker service rm "$svc" >/dev/null 2>&1 || true
docker service create --detach --quiet \
  --name "$svc" \
  --with-registry-auth \
  --restart-condition none \
  --network "${STACK}_internal" \
  --constraint node.hostname==dev-worker-1 \
  --env-file aivee.env \
  --env POSTGRES_HOST=postgres --env POSTGRES_PORT=5432 \
  "$IMAGE" "${cmd[@]}" >/dev/null

state=""
for _ in $(seq 1 120); do
  state="$(docker service ps "$svc" --format '{{.CurrentState}}' | head -1)"
  case "$state" in Complete*|Failed*|Rejected*) break ;; esac
  sleep 2
done
docker service logs --raw "$svc" 2>&1 | tail -50
docker service rm "$svc" >/dev/null
echo "$svc: $state"
[[ "$state" == Complete* ]]
