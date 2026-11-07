# AiVee presentation site: the static build (node build.mjs) served by nginx.
# Build from the repo root: docker build -f apps/site/Dockerfile .
FROM node:24-alpine AS build
WORKDIR /app
COPY docs/brand docs/brand
COPY apps/site apps/site
RUN cd apps/site && node build.mjs

FROM nginx:1.29-alpine
COPY --from=build /app/apps/site/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
