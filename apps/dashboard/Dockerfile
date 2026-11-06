# AiVee dashboard: the production build served by nginx, with /api, /ws and /healthz proxied
# to the api service on the same origin, so the session cookie needs no CORS.
# Build from the repo root:
#   docker build -f apps/dashboard/Dockerfile \
#     --build-arg VITE_API_URL=https://app-aivee.earth.sv.gsd.com.ro .
# VITE_API_URL must be the public origin (an empty value builds the in-browser mock).
FROM node:24-alpine AS build
WORKDIR /app/apps/dashboard
COPY apps/dashboard/package.json apps/dashboard/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY apps/dashboard ./
ARG VITE_API_URL
# Live video: no MediaMTX on the server; a same-origin path that answers 404 makes the
# player fall back to the placeholder at once instead of probing the viewer's localhost.
ARG VITE_WHEP_BASE=/no-whep
ENV VITE_API_URL=$VITE_API_URL VITE_WHEP_BASE=$VITE_WHEP_BASE
RUN test -n "$VITE_API_URL" || { echo "VITE_API_URL is required" >&2; exit 1; }
RUN npm run build

FROM nginx:1.29-alpine
COPY apps/dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/dashboard/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
