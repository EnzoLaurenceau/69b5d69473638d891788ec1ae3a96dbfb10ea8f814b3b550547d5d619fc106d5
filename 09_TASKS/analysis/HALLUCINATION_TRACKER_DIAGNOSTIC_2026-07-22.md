# Diagnostic — Tracker d'hallucinations du dashboard : pourquoi il n'était pas temps réel

**Date :** 2026-07-22
**Fichiers :** `09_WEB/server.py`, `09_WEB/static/index.html`,
`scripts/forge_telemetry_daemon.py`, `00_CORE/forge_agents/hallucination_compare.py`

---

## 0. Réponse courte

**Le tracking ne se déroulait pas.** Le dernier événement enregistré datait du
**2026-07-18 14:45**, soit **6 043 minutes (4,2 jours)** avant le diagnostic —
alors que **1 586 hallucinations inédites attendaient dans le ledger**, déjà
détectables, jamais persistées.

Le frontend n'était pas en cause : il rafraîchissait déjà l'onglet toutes les
3 s. Il affichait fidèlement un fichier mort.

État mesuré avant / après :

| | Avant | Après |
|---|---|---|
| `status` | **dead** | **live** |
| Minutes depuis la dernière écriture | 6 043 | 0 |
| Événements | 500 (au plafond) | 1 814 |
| Ids uniques | **391 / 500** | 1 814 / 1 814 |
| Producteur planifié | aucun | daemon, toutes les 60 s |
| Push WebSocket | jamais déclenché | watcher fichier, 2 s |

---

## 1. Les cinq causes

### Cause n°1 — aucun producteur n'était planifié (la cause principale)

La chaîne réelle est :

```
Hermes DB + transcripts Claude Code
   → tool_call_ledger.build_ledger()      → 05_STATE/tool_call_ledger.jsonl
   → hallucination_compare.scan_ledger()  → findings
   → save_findings()                      → 05_STATE/hallucination_events.json
```

Le seul appelant de cette chaîne était
`scripts/hermes_session_tracker.py::update_hallucinations()`. Or **aucun fichier
du dépôt ne référence `hermes_session_tracker`** en dehors d'un chemin de repli
mort dans `server.py` (il n'est atteint que si `forge_telemetry_daemon` échoue à
l'import — ce qui n'arrive pas).

Le daemon qui tourne réellement (`ForgeTelemetryDaemon.update_dashboard()`,
toutes les 5 s depuis le serveur) **comptait** les findings pour les statistiques
(`hallucination_findings_count`) mais n'en **persistait aucun**. Il lisait sans
jamais écrire.

**Corrigé** : `_update_hallucinations()` ajouté au daemon et appelé depuis
`update_dashboard()`. Throttlé à 60 s (`HALLUC_SCAN_INTERVAL_SEC`) — le scan
compare le texte de ~1 000 enregistrements, le refaire toutes les 5 s serait du
gaspillage pour un tracker dont la granularité utile est humaine.

### Cause n°2 — le producteur court-circuitait le transport

`POST /api/hallucinations/report` diffuse bien un `HALLUCINATION_DETECTED` en
WebSocket. Mais le producteur écrit le fichier JSON **directement**
(`save_findings()` → `_save_hallucinations()`), sans passer par l'API.
**Le broadcast n'était donc jamais déclenché**, quel que soit le nombre
d'événements écrits.

**Corrigé** : `_hallucination_watcher()` — tâche asyncio lancée au démarrage, qui
surveille le `mtime` du fichier toutes les 2 s et diffuse tout événement dont
l'id n'a pas encore été vu. Le temps réel devient **indépendant du producteur** :
peu importe qui écrit (daemon, script manuel, API), le dashboard est notifié.
Diffusion bornée à 20 événements + un message `HALLUCINATION_BATCH` agrégé, pour
qu'un scan produisant 1 265 événements ne noie pas le flux.

### Cause n°3 — les ids étaient recyclés (`/resolve` marquait le mauvais événement)

```python
"id": len(events) + 1        # puis: if len(events) > 500: events = events[-500:]
```

Une fois le plafond atteint, les plus anciens sont éliminés, `len(events)` cesse
de croître et les ids **se répètent**. Mesuré : **391 ids uniques pour 500
événements — 109 doublons**. `POST /api/hallucinations/{id}/resolve` s'arrête au
premier id correspondant : il marquait donc régulièrement un autre événement que
celui affiché.

**Corrigé** : `_next_halluc_id()` / `next_event_id()` = `max(ids) + 1`, dans
`server.py` **et** `hallucination_compare.py` (les deux écrivent le même
fichier). Endpoint `POST /api/hallucinations/repair-ids` pour l'historique —
exécuté : **109 ids réparés, 1 765 ids uniques sur 1 765**.

### Cause n°4 — le plafond jetait silencieusement les findings

`MAX_EVENTS = 500`. Le premier scan réel a produit **1 586 findings inédits** :
1 086 auraient été supprimés sans trace.

**Corrigé** : plafond porté à **2 000**, constante alignée des deux côtés
(`hallucination_compare.MAX_EVENTS` / `server.MAX_HALLUC_EVENTS`). Le champ
`at_cap` de `/health` signale explicitement l'atteinte du plafond au lieu de
tronquer en silence.

### Cause n°5 — l'horodatage était celui du scan, pas de l'hallucination

`"timestamp": datetime.now().timestamp()` était posé au moment de
l'enregistrement. Conséquence : un re-scan faisait apparaître des hallucinations
vieilles de plusieurs jours comme « il y a 5 secondes », et le KPI **`24h`
mentait** — il comptait des scans, pas des occurrences.

**Corrigé** : `timestamp` = instant réel de l'appel d'outil fautif (issu du
ledger, via `context.timestamp`) ; l'instant du scan est conservé séparément dans
un nouveau champ **`detected_at`**.

---

## 2. Ce que le frontend ne disait pas

Le tracker mort et le tracker sans rien à signaler affichaient **exactement le
même écran** : « Aucune hallucination enregistrée », tous les KPIs à 0. Rien ne
permettait de distinguer « tout va bien » de « le producteur est arrêté depuis
4 jours ».

Ajouts dans `index.html` :

- **Badge de fraîcheur** (`● LIVE / STALE / DEAD · dernier scan Xmin`) alimenté
  par `/api/hallucinations/health`, avec infobulle détaillée (dernière
  occurrence, dernière détection, écriture du ledger, watcher actif, remplissage
  du plafond).
- **Bouton `⟳ Scan`** — déclenche un scan réel immédiat et rapporte le résultat
  dans le flux d'événements.
- **Rafraîchissement même onglet fermé** — auparavant
  `if (!tabHidden) loadHallucinations()` jetait purement l'update. Désormais
  l'onglet est marqué *dirty*, une pastille rouge apparaît sur l'onglet, et le
  rechargement se fait à l'ouverture.
- Gestion du message `HALLUCINATION_BATCH`.

---

## 3. Vérification exécutée

```
/api/hallucinations/health   avant : status=dead, 6043 min, 391 ids uniques/500
POST /api/hallucinations/scan      : 1000 records ledger → 1341 findings
                                     → 1265 nouveaux événements
POST /api/hallucinations/repair-ids: 109 ids réparés → 1765 uniques/1765
/api/hallucinations/health   après : status=live, 0 min, 0 doublon
daemon _update_hallucinations(force=True) → 49 nouveaux événements
daemon _update_hallucinations()           → 0 (throttling à 60 s vérifié)
watcher (test avec WebSocket simulé)      → 2 messages diffusés
                                            (HALLUCINATION_DETECTED + BATCH)
```

L'événement de test injecté pour valider le watcher a été retiré du store
(1 814 événements réels restants).

---

## 4. Ce qui reste à surveiller

- Le ledger est **plafonné à 500 enregistrements par source** (Hermes + Claude
  Code = 1 000). Sur une journée très active, des appels d'outils peuvent sortir
  de la fenêtre entre deux scans de 60 s. Si cela devient réel, il faudra passer
  l'ingestion en mode incrémental (curseur sur le dernier timestamp ingéré)
  plutôt qu'en « derniers N ».
- Le détecteur est **syntaxique** (grounding numérique, négation, masquage
  d'erreur). Sévérité `low` très majoritaire : c'est un signal de revue, pas un
  verdict. Un juge sémantique existe (`hallucination_judge.py`) mais n'est pas
  branché sur cette chaîne.
- Les 2 000 événements du plafond seront atteints ; prévoir une archive
  glissante plutôt qu'une troncature.
