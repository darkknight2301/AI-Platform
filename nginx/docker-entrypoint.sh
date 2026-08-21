#!/bin/sh
# Renders nginx.conf.template -> /etc/nginx/nginx.conf by substituting
# __PLACEHOLDER__ tokens with environment variables. Runs as an
# official nginx image docker-entrypoint.d/ script, so it executes
# automatically before nginx starts (and before the base image's own
# templating hook, since 50- sorts before its 99-default hooks run —
# safe either way since this only touches the file we control).
#
# Required env vars (set per environment — see ../DEPLOYMENT.md):
#   SERVER_NAME       e.g. app.example.com
#   SSL_CERT_PATH     path inside the container to fullchain.pem (staging/prod)
#   SSL_KEY_PATH      path inside the container to privkey.pem   (staging/prod)
# Required env vars (set per environment — see ../DEPLOYMENT.md):
#   SERVER_NAME       e.g. app.example.com
#   SSL_CERT_PATH     path inside the container to fullchain.pem (staging/prod)
#   SSL_KEY_PATH      path inside the container to privkey.pem   (staging/prod)
#   API_UPSTREAM      host:port of the backend (default: docker-compose service name)
set -eu

SERVER_NAME="${SERVER_NAME:-localhost}"
SSL_CERT_PATH="${SSL_CERT_PATH:-/etc/nginx/ssl/fullchain.pem}"
SSL_KEY_PATH="${SSL_KEY_PATH:-/etc/nginx/ssl/privkey.pem}"
API_UPSTREAM="${API_UPSTREAM:-backend:8000}"

sed \
    -e "s#__SERVER_NAME__#${SERVER_NAME}#g" \
    -e "s#__SSL_CERT_PATH__#${SSL_CERT_PATH}#g" \
    -e "s#__SSL_KEY_PATH__#${SSL_KEY_PATH}#g" \
    -e "s#__API_UPSTREAM__#${API_UPSTREAM}#g" \
    /etc/nginx/templates/nginx.conf.template > /etc/nginx/nginx.conf

echo "nginx.conf rendered for server_name=${SERVER_NAME}"
