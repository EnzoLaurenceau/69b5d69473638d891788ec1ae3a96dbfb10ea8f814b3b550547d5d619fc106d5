# RUNBOOK — Plateforme d'inférence La Forge (Phase 4)

> Exploitation de la plateforme `/v1` en production (cible **Coolify**, doctrine
> microservices). Ce runbook couvre les gestes opérateur : démarrer, provisionner un
> tenant, révoquer un jeton, lire les métriques, **rollback**. Complète le plan
> (`PLAN_PLATEFORME_INFERENCE.md`) et le handoff (`HANDOFF_PLATEFORME_INFERENCE.md`).

## 0. Architecture déployée
```
[navigateur] → console (nginx :8080) ──proxy /v1──▶ api (:7777) ──▶ postgres / redis
                                                        └── /metrics ◀── prometheus (interne)
```
- **api** : façade `/v1` + dashboard `server.py`. VRAI multi-tenant (auth Bearer, Phase 3).
- **console** : SPA React servie par nginx, proxifie `/v1` (REST + WS) vers `api`.
- **postgres / redis** : datastores (réseau interne, aucun port exposé).
- **prometheus** : scrape `/metrics` (agrégé, sans donnée tenant) sur le réseau interne.

## 1. Démarrer (reproductible depuis zéro)
```bash
git clone <forge-core> && cd forge-core
cp .env.example .env          # renseigner POSTGRES_PASSWORD, FORGE_ADMIN_TOKEN, FORGE_CORS_ORIGINS
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps        # tous les services "healthy"
curl -fsS http://localhost:7777/api/health          # sonde API
```
> Sur Coolify : pointer le projet sur ce repo, fichier compose `docker-compose.prod.yml`,
> renseigner les variables d'environnement dans l'UI (elles remplacent `.env`), déployer.
> Le reverse-proxy (Traefik) gère TLS + rate-limit d'edge devant l'`api` et la `console`.

## 2. Provisionner un tenant (rôle opérateur)
Le jeton opérateur (`FORGE_ADMIN_TOKEN`) est **distinct** des jetons tenant. Un jeton
tenant ne peut jamais ouvrir `/v1/admin/*`.
```bash
OP="Authorization: Bearer $FORGE_ADMIN_TOKEN"
# créer un tenant + jeton (+ limites optionnelles)
curl -sX POST http://localhost:7777/v1/admin/tenants -H "$OP" -H "Content-Type: application/json" \
     -d '{"tenant_id":"acme","limits":{"requests":1000}}'
#  → {"tenant_id":"acme","token":"<JETON_TENANT>","limits":{...}}   (jeton affiché UNE fois)

# lister les tenants (vue opérateur, sans secret)
curl -sX GET http://localhost:7777/v1/admin/tenants -H "$OP"
```
Le client utilise ensuite son jeton : `Authorization: Bearer <JETON_TENANT>` sur `/v1/*`.

## 3. Faire tourner / révoquer un jeton
```bash
OP="Authorization: Bearer $FORGE_ADMIN_TOKEN"
# rotation (l'ancien jeton cesse immédiatement d'être valide)
curl -sX POST http://localhost:7777/v1/admin/tenants/acme/tokens -H "$OP" \
     -H "Content-Type: application/json" -d '{"action":"issue"}'
# révocation (le tenant est désactivé : ses jetons renvoient 401)
curl -sX POST http://localhost:7777/v1/admin/tenants/acme/tokens -H "$OP" \
     -H "Content-Type: application/json" -d '{"action":"revoke"}'
```

## 4. Lire les métriques
- **Produit (par tenant)** : `GET /v1/metrics` avec le jeton tenant → tokens, coût, économie RTK.
- **Quota (par tenant)** : `GET /v1/quota` → consommation / limites / fenêtre.
- **Ops (agrégé, Prometheus)** : `GET /metrics` (scrape interne) → cache, CPU/RAM, tokens économisés.
  Aucune donnée tenant ; à brancher dans Grafana/LangSmith côté observabilité.

## 5. Gates de livraison (à repasser avant tout déploiement)
```bash
python 00_CORE/tools/state_ownership.py --check     # cloisonnement d'état (doit être PORTE OK)
python 00_CORE/tools/security_audit.py  --check     # 0 route non gardée, 0 HIGH non revu
python -m pytest -q                                 # suite complète (dont isolation Phase 3)
```
- **Herald** (gate MVP, grade ≥ B, sécu ≥ 70) : service Rust externe. Deux modes :
  `cd AsyncHerald && docker build -t herald . && docker run -p 3001:80 --env-file .env herald`
  puis `POST http://localhost:3001/analyze/local`. Ou API cloud `app.itsasync.fr/herald`.
  **N'a pas pu être exécuté dans l'environnement de dev** (sous-module non initialisé, Docker
  absent du shell) → à lancer sur la machine de déploiement. La dimension sécurité locale est
  couverte en attendant par `security_audit.py` (déterministe, vert).

## 6. Rollback
Le code est **figé dans l'image** (`forge-api:prod`, `forge-console:prod`) — pas de mount.
Revenir à la version précédente = redéployer l'image précédente :
```bash
# 1. identifier le commit/tag précédent (les images sont taguées par commit en CI/registry)
git log --oneline -5
# 2. sur Coolify : sélectionner le déploiement précédent → "Redeploy" (image déjà buildée)
#    ou en CLI :  docker compose -f docker-compose.prod.yml up -d --no-build  (avec l'image épinglée)
# 3. données : les volumes (forge_pgdata/redisdata/state) SURVIVENT au rollback.
#    Migration réversible : aucune migration destructive n'est appliquée au démarrage
#    (schema.sql est idempotent, l'état forge_store est additif) → rollback sûr sans restore.
```
> Point de vigilance : un jeton émis par la version N reste valide après rollback en N-1
> (registre d'identité persistant). Pour invalider, révoquer explicitement (§3).

## 7. Incidents fréquents
| Symptôme | Cause probable | Geste |
|---|---|---|
| `/v1/*` → 401 partout | jeton tenant absent/révoqué, ou horloge/registre | vérifier le jeton, `GET /v1/admin/tenants` |
| `/v1/admin/*` → 403 | `FORGE_ADMIN_TOKEN` absent/incorrect | vérifier la variable d'env du service `api` |
| run bloqué "en cours" | backend LLM FREE injoignable | vérifier les clés LLM `.env` (jamais d'API Anthropic au token) |
| quota 429 permanent | limite tenant trop basse | ajuster via `POST /v1/admin/tenants` (limits) |
| écritures "espace GLOBAL" | `FORGE_TENANT_STRICT` absent + requête hors tenant | garder `FORGE_TENANT_STRICT=1` en prod |
