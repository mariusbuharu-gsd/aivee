#!/usr/bin/env bash
# Build the aivee-demo images on a laptop and push them to Nexus (the manager has no GitHub key).
#
#   deploy/aivee-demo/build.sh                 # every image, tagged with the current commit
#   deploy/aivee-demo/build.sh api dashboard   # only these
#   TAG=mytag deploy/aivee-demo/build.sh site
#   MODELS=/path/to/models deploy/aivee-demo/build.sh vision   # cloud vision worker (+ models)
#
# Needs `docker login docker-hub.gsd.com.ro` once. Prints the tag to deploy at the end.
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
REG="${REGISTRY:-docker-hub.gsd.com.ro/aivee}"
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short=8 HEAD)}"
APP_URL="${APP_URL:-https://app-aivee.earth.sv.gsd.com.ro}"
ALL=(api ingest dashboard site mosquitto)

if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
  echo "build: the working tree has uncommitted changes; the tag $TAG will not match them" >&2
fi

build() { # name dockerfile [extra docker build args...]
  local name="$1" file="$2"; shift 2
  echo "==> $REG/$name:$TAG"
  docker build -f "$ROOT/$file" -t "$REG/$name:$TAG" "$@" "$ROOT"
  docker push "$REG/$name:$TAG"
}

for svc in "${@:-${ALL[@]}}"; do
  case "$svc" in
    api) build api apps/api/Dockerfile --build-arg UV_EXTRAS="${API_UV_EXTRAS:-}" ;;
    ingest) build ingest apps/ingest/Dockerfile ;;
    dashboard) build dashboard apps/dashboard/Dockerfile --build-arg VITE_API_URL="$APP_URL" ;;
    site) build site apps/site/Dockerfile ;;
    mosquitto) build mosquitto deploy/aivee-demo/mosquitto.Dockerfile ;;
    vision)
      # The edge image plus the OpenVINO models (models/ is gitignored, so it is a second
      # build context; download with: uv run python tools/download_models.py).
      MODELS="${MODELS:-$ROOT/models}"
      [[ -d "$MODELS" ]] || { echo "build: no models dir at $MODELS" >&2; exit 1; }
      docker build -f "$ROOT/apps/edge/Dockerfile" -t "aivee-edge-base:$TAG" "$ROOT"
      build vision deploy/aivee-demo/vision.Dockerfile \
        --build-arg BASE="aivee-edge-base:$TAG" --build-context models="$MODELS" ;;
    *) echo "build: unknown image '$svc' (${ALL[*]} vision)" >&2; exit 2 ;;
  esac
done

echo
echo "Pushed tag: $TAG"
echo "On the manager: cd ~/aivee-demo && TAG=$TAG docker stack deploy --with-registry-auth -c stack.yml aivee-demo"
