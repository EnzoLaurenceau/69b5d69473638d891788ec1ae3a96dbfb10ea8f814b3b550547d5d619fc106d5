# docker/api.Dockerfile — image de dev pour la plateforme d'inférence (Phase 1, local).
# Pas encore l'image de prod Coolify (Phase 4) : ici on optimise l'itération (bind-mount),
# pas la taille de l'image.

FROM python:3.11-slim

WORKDIR /app

# Dépendances système minimales pour psycopg[binary]/redis (déjà "binary", donc léger).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Le code réel arrive par bind-mount (docker-compose.local.yml) — COPY sert de repli
# si l'image est construite sans mount (ex. build de vérification en CI).
COPY . .

EXPOSE 7777

CMD ["python", "09_WEB/server.py"]
