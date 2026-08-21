# Builds the static SPA bundle. This image is not run as a service —
# its only job is to produce /app/dist, which docker-compose copies
# (via a shared volume, or a `COPY --from=` in nginx/Dockerfile) into
# the nginx container that actually serves it. See ../DEPLOYMENT.md,
# "Nginx" — the architecture diagram puts Nginx directly in front of
# the built frontend, not a Node process.

FROM node:20-slim AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
# VITE_* build-time env vars (e.g. API base path) are baked into the
# bundle here, not read at container-start — see DEPLOYMENT.md,
# "Environments" for how dev/staging/production differ on this.
RUN npm run build

FROM scratch AS export
COPY --from=build /app/dist /dist
