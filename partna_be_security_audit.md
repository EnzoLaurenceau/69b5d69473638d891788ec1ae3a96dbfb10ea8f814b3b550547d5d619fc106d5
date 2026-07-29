# Audit sécurité — partna.be

**Date :** 2026-07-20 · **Autorisation :** propriétaires (Julius & Matthis) · **Objectif :** refonte 100 % sécurisée + retrait AI-slop
**Type :** actif + PoC non-destructif · **Moteur :** Claude (abonnement, pas de clés API) · recon via WSL Parrot (curl/subfinder/nuclei)

---

## 1. Surface d'attaque

Stack : **Next.js (Turbopack) sur Vercel** + backend API séparé.

| Host | Rôle | Auth |
|---|---|---|
| `www.partna.be` | Vitrine (statique) | — |
| `ads.partna.be` | SaaS gestion Google Ads | oui (→ `/login`) |
| `assistant.partna.be` | Assistant IA (chat) | oui (→ `/chat`) |
| `analyseperso.partna.be` | Landing / funnel (Calendly, monentreprise.be) | — |
| `partna-ads-api.vercel.app` | **Backend API** (`{"service":"Partna Ads API","version":"2.0"}`) | Bearer token |

Endpoints backend cartographiés (depuis le JS client) : `/api/auth/{login,signup,me}`, `/api/admin/{clients,stats}`, `/api/campaigns/*`, `/api/google/*`, `/api/billing/*`, `/api/assets/{upload-url,finalize}`, `/api/alerts`, `/api/chat/*`, `/api/oauth/`, `/api/connections`, `/api/settings`.

---

## 2. Ce qui est SÛR (validé, à conserver dans la refonte)

- ✅ **Backend auth robuste** — tous les endpoints, **admin inclus**, renvoient `401 {"error":"Non authentifié"}` sans token. Pas de broken access control / IDOR sur les endpoints testés.
- ✅ **Pas vulnérable à CVE-2025-29927** (bypass middleware Next.js) — `/` reste `307→/login` avec et sans header `x-middleware-subrequest`.
- ✅ **Aucun secret dans le JS client** — pas de clé API / JWT / Supabase / OpenAI / Anthropic hardcodée dans les bundles (2,8 Mo scannés).
- ✅ **Pas d'énumération d'utilisateur** — login renvoie un message générique (`Email ou mot de passe incorrect`).
- ✅ **Aucun fichier sensible exposé** — `.env`, `.git/config`, `openapi.json`, `swagger`, `/api/debug` → tous 404.
- ✅ **HSTS actif partout** (backend : `includeSubDomains; preload`).
- ✅ **nuclei** (13 060 templates, CVE/misconfig/exposure/CORS/SSL) → **0 finding**.

---

## 3. Findings (à corriger dans la refonte)

### 🟠 F-01 — MEDIUM · Pas de rate-limiting sur le login
**Où :** `POST partna-ads-api.vercel.app/api/auth/login`
**Preuve :** 12 requêtes rapides (email bidon) → `401 401 401 ... 401`, **aucun 429**, aucun header `retry-after` / `x-ratelimit`.
**Impact :** brute-force / password-spraying possible → prise de compte sur mots de passe faibles.
**Fix :** rate-limit par IP + par compte (ex. `@upstash/ratelimit` + Redis, ou Vercel Firewall), backoff exponentiel, lockout temporaire, CAPTCHA après N échecs.

### 🟠 F-02 — MEDIUM · Token d'auth en `localStorage`
**Où :** `ads` + `assistant` — JS : `localStorage.getItem("partna_token")`, envoyé en `Authorization: Bearer`.
**Impact :** toute XSS = **exfiltration du token → account takeover complet** (le token est lisible en JS). Aggravé par F-03 (pas de CSP). Viole aussi la règle « pas de localStorage » de la refonte.
**Fix :** cookie **`httpOnly` + `Secure` + `SameSite=Lax/Strict`** posé par le backend ; le JS ne touche jamais le token. Rotation + expiration courte + refresh token.

### 🟡 F-03 — MEDIUM · Headers de sécurité absents (tous les frontends)
**Où :** `www`, `ads`, `assistant`, `analyseperso`.
**Manquants :** `Content-Security-Policy`, `X-Frame-Options` (ou CSP `frame-ancestors`), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`. (HSTS présent ✅.)
**Impact :** clickjacking (pas de `frame-ancestors`), et surtout **XSS non contenue** — c'est le multiplicateur de F-02.
**Fix :** `next.config.js` → `headers()` avec CSP stricte (nonce), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` minimal.

### 🟡 F-04 — MEDIUM · Email spoofing (SPF + DMARC absents)
**Où :** DNS `partna.be`.
**Preuve :** `No SPF record` · `No DMARC policy`. (DKIM Google présent.)
**Impact :** n'importe qui peut envoyer des mails usurpant `@partna.be` (phishing clients).
**Fix :** `SPF` (`v=spf1 include:_spf.google.com -all`) + `DMARC` (`v=DMARC1; p=quarantine` → `p=reject` après monitoring `rua`).

### 🟡 F-05 — LOW · CORS backend mal configuré
**Où :** `partna-ads-api.vercel.app`.
**Preuve :** `access-control-allow-credentials: true` + `access-control-allow-origin: http://localhost:3001` (origine **dev en dur, en prod**). Origine arbitraire (`evil.example`) non reflétée → **pas exploitable aujourd'hui** (auth par Bearer, pas cookie).
**Impact :** faible maintenant, mais devient dangereux si vous passez aux cookies (F-02) sans corriger l'allowlist. Config incohérente.
**Fix :** allowlist d'origines de prod explicite (`https://ads.partna.be`, `https://assistant.partna.be`) ; `allow-credentials: true` **seulement** avec cookies + origine exacte.

### 🔵 F-06 — LOW · Garde d'auth uniquement côté client sur `/dashboard`
**Où :** `ads.partna.be/dashboard` → **200 sans token** (le squelette de page se charge ; `/` fait bien `307→/login`).
**Impact :** pas de fuite de données (le backend renvoie 401), mais structure de l'app exposée + incohérence d'auth.
**Fix :** protéger la route côté serveur (middleware / RSC redirect) en plus du check client.

### ℹ️ F-07 — INFO
- `access-control-allow-origin: *` sur les assets statiques Vercel (défaut, faible risque — contenu statique, pas de credentials).
- Version disclosure : backend `/` expose `version:"2.0"` (négligeable).

---

## 4. Priorités refonte (ordre)

1. **F-02 + F-03 ensemble** — cookie httpOnly + CSP stricte (casse la chaîne XSS→takeover). *Impact sécurité max.*
2. **F-01** — rate-limit login.
3. **F-04** — SPF/DMARC (5 min, DNS).
4. **F-05 / F-06** — CORS allowlist prod + garde serveur sur routes protégées.

Note « AI-slop » : à traiter à la refonte (prompts assistant, textes génériques) — non testable ici car le chat est derrière auth (401). À auditer côté code/prompts une fois l'accès repo fourni.

---
*Testé le 2026-07-20 — aucune donnée réelle extraite, aucun compte créé, aucune perturbation de service. PoC limité à la vérification (statuts HTTP, 12 tentatives login sur email fictif).*
