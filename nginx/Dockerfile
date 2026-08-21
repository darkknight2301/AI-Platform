# Serves the built frontend and reverse-proxies /api/ to the backend.
# See ../DEPLOYMENT.md, "Nginx". Built in two stages so this image
# never needs Node.js at runtime — only the compiled static output.

FROM node:20-slim AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=frontend-build /app/dist /var/www/frontend/dist
COPY nginx/nginx.conf.template /etc/nginx/templates/nginx.conf.template

# Real deployments substitute __SERVER_NAME__ / __SSL_CERT_PATH__ /
# __SSL_KEY_PATH__ (and any other __PLACEHOLDER__) at container start
# via this entrypoint script, then hand off to nginx's own image
# entrypoint so its usual template/signal handling still applies.
COPY nginx/docker-entrypoint.sh /docker-entrypoint.d/50-render-template.sh
RUN chmod +x /docker-entrypoint.d/50-render-template.sh

EXPOSE 80 443
