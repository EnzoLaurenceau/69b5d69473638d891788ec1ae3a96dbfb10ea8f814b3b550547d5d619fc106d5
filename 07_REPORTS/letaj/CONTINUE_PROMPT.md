# Claude CLI — brief de continuation : audit sécurité/RGPD letaj.be

> Lancer :  `claude -p "$(cat 07_REPORTS/letaj/CONTINUE_PROMPT.md)"`
> ou coller le bloc ci-dessous dans une session `claude` fraîche.

---

## ⛔ RÈGLE D'ENGAGEMENT — À LIRE EN PREMIER (non négociable)

`letaj.be` tourne sur l'infra de **Just Eat Takeaway** (NS `*.takeaway.com`, hébergement AWS eu-west-1).
Le restaurant Le Taj (TVA BE0477225548) est un **partenaire/locataire**, pas l'opérateur des serveurs.
→ **Aucune** autorisation de scan actif (nuclei/sqlmap/nmap/brute-force/fuzzing/exploit) sur cette infra
  tant qu'il n'existe pas une autorisation écrite **in-scope** de Just Eat Takeaway.

AUTORISÉ (aucun trafic d'attaque, légal partout) :
- OSINT passif (DNS, WHOIS, Certificate Transparency / crt.sh, archives, métadonnées publiques)
- Lecture des documents publics (privacy/cookies/terms/mentions)
- Observation en **navigateur normal** (ce qu'un visiteur voit : cookies déposés, en-têtes, trackers)
- Mapping d'actifs via sources passives uniquement

INTERDIT sans autorisation écrite in-scope JET :
- Tout envoi de payload, injection, fuzzing, force brute, énumération agressive, test d'exploit CVE actif

Si un vrai défaut est trouvé → **divulgation responsable** via le programme JET, jamais d'exploitation.

---

## CONTEXTE — déjà établi (session précédente)

Cible : `https://www.letaj.be` (Le Taj, resto indien, Saint-Gilles 1060).
Responsable du traitement = **Takeaway.com Group B.V.** (Amsterdam), DPO Piet Heinkade 61.

Findings confirmés (passifs) :
1. **Email spoofable** — aucun SPF, aucun DMARC, aucun DKIM sur `letaj.be` → usurpation `@letaj.be` triviale (phishing clients).
2. **En-têtes de durcissement absents** — pas de HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
3. **Consentement cookies à vérifier** — cookie statement en logique opt-out périmée ; annonce cookies analytiques + marketing tiers. Question décisive APD non tranchée : *des trackers se déposent-ils AVANT consentement ?* (fetch sans JS = 0 cookie, non concluant).
Bon point : HTTP→HTTPS forcé (301), docs RGPD complets (bases légales, droits, transferts/SCC, DPO, profilage).

## MISSION

Approfondir UNIQUEMENT les lanes légitimes ci-dessous, produire des findings reportables et un rapport.

### 1. Test consentement cookies (navigateur JS — observationnel, = visite normale)
- Charger letaj.be en navigateur réel (firecrawl-interact ou Claude-in-Chrome).
- AVANT tout clic : lister cookies + requêtes réseau sortantes (analytics/marketing/pixels tiers).
- Verdict ePrivacy/APD : non-essentiels déposés avant opt-in = non-conformité (le point le plus contentieux).
- Capturer : présence/absence d'un CMP, granularité (accepter/refuser/personnaliser), équivalence des boutons.

### 2. Posture en-têtes + TLS (passif)
- Relever en-têtes réponse, version TLS, ciphers, redirection, cookies `Secure`/`HttpOnly`/`SameSite`.
- Mapper chaque manque sur l'impact (clickjacking, MITM, fuite referrer) — pas d'exploit, juste constat.

### 3. Email auth (passif)
- Documenter SPF/DMARC/DKIM manquants → scénario d'abus (phishing usurpant le resto) + correctif DNS exact.

### 4. Surface publique (passif)
- crt.sh / Certificate Transparency, sous-domaines via sources passives, `security.txt`, archives.
- Repérer le **programme de divulgation responsable / bug bounty de Just Eat Takeaway** + son scope.
  → C'est CE programme qui définit ce qui devient testable activement et comment reporter.

### 5. Livrables (fichiers, jamais inline)
- `07_REPORTS/letaj/RGPD_AUDIT.md` — conformité mappée article par article (RGPD + ePrivacy/loi belge).
- `07_REPORTS/letaj/SECURITY_FINDINGS.md` — findings techniques, sévérité, preuve passive, correctif.
- `07_REPORTS/letaj/RESPONSIBLE_DISCLOSURE.md` — brouillon de rapport prêt à soumettre au programme JET.

## OUTILLAGE DISPO DANS LA FORGE
- MCP `openosint` : search_dns / search_whois / search_domain / search_shodan / scrape_url (passif).
- `context-mode` : ctx_fetch_and_index (pages), ctx_search, ctx_execute (analyse) — garder le brut hors contexte.
- Skill `hackingtool:pentest` & `hexstrike-ai` : **seulement** sur des actifs que TU possèdes/autorisés, pas l'infra JET.
- `cvelistV5-main/` : corpus CVE local pour mapper une techno→CVE (analyse documentaire, pas exploit).

## CRITÈRE DE FIN
- Test cookie tranché (oui/non trackers pré-consentement, avec preuve).
- 3 fichiers livrables écrits.
- Aucun trafic d'attaque émis. Tout finding routé vers divulgation responsable.
