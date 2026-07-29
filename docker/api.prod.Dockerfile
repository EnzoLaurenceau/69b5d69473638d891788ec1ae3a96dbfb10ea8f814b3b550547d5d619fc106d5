# docker/api.prod.Dockerfile — image de PRODUCTION de la plateforme d'inférence (Phase 4).
#
# Différences avec api.Dockerfile (dev) : pas de bind-mount (code FIGÉ dans l'image →
# reproductible + rollback = image précédente), utilisateur NON-root, healthcheck intégré.
# Décision verrouillée #1 : 1 process (le repli fichier de forge_store est intra-process ;
# on ne lance donc PAS de multi-worker partagé — cf. blueprint §6).

FROM python:3.11-slim

# N'écrit pas de .pyc, sort les logs sans buffer (utile en conteneur), pip silencieux.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WEB_PORT=7777

WORKDIR /app

# Dépendances système minimales (psycopg[binary]/redis sont déjà en wheels binaires).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Couche de dépendances séparée : le cache ne s'invalide que si requirements.txt change.
COPY requirements-docker.txt requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Code applicatif (figé dans l'image — aucun mount en prod).
COPY . .

# Utilisateur non-root : le process serveur n'a jamais les droits root dans le conteneur.
# Il doit pouvoir écrire l'état runtime (05_STATE, monté en volume par le compose).
RUN useradd --create-home --uid 10001 forge \
    && mkdir -p /app/05_STATE /app/08_LOGS \
    && chown -R forge:forge /app/05_STATE /app/08_LOGS
USER forge

EXPOSE 7777

# Healthcheck : la route /api/health de server.py (publique par conception).
HEALTHCHECK --interval=15s --timeout=5s --retries=6 --start-period=30s \
    CMD curl -fsS "http://localhost:${WEB_PORT}/api/health" || exit 1

CMD ["python", "09_WEB/server.py"]
