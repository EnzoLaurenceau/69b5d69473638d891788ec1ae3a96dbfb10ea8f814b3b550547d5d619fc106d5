# console/Dockerfile — image de PRODUCTION de la console Forge (Phase 4).
#
# Multi-stage : Node build → Nginx serve. La console est une SPA React/Vite
# servie statiquement, avec un proxy /v1 vers l'API sur le réseau interne.
#
#   docker build -t forge-console:prod ./console
#   docker run -p 8080:80 forge-console:prod

# ── Stage 1 : build ──────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Cache npm : on copie d'abord les dépendances, puis le code.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ── Stage 2 : serve ──────────────────────────────────────────────────
FROM nginx:stable-alpine

# Copier la config nginx (proxy /v1 → api:7777, SPA fallback).
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copier les assets buildés depuis le stage builder.
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=6 --start-period=10s \
    CMD wget -qO- http://127.0.0.1:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
