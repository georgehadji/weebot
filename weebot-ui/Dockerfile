# Placeholder image — the Next.js frontend source isn't in this repo yet.
# Serves a static "not yet available" page so `docker compose up` and CI's
# Docker build smoke test succeed. Replace with a real Next.js build once
# the weebot-ui frontend source is added.
#
# Intentionally copies nothing from the build context so this Dockerfile
# builds the same way regardless of context root (CI builds with context
# `weebot-ui/`, docker-compose builds with context `.`).
FROM nginx:alpine

RUN set -eux; \
    printf '<!doctype html>\n<html><head><title>Weebot UI</title></head>\n<body style="font-family: system-ui, sans-serif; max-width: 640px; margin: 4rem auto; padding: 0 1rem;">\n<h1>Weebot UI</h1>\n<p>The frontend source isn'"'"'t included in this image yet. Use the API directly, or run <code>weebot-ui</code> from source once it'"'"'s added to the repo.</p>\n</body></html>\n' > /usr/share/nginx/html/index.html; \
    printf 'server {\n    listen 3000;\n    server_name _;\n    location / {\n        root /usr/share/nginx/html;\n        index index.html;\n    }\n}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
