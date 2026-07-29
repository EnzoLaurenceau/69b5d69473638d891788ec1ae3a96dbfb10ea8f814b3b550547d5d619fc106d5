# Debug — faire livrer Site B en autonome par la Forge

Objectif : `run_forge.py` doit écrire les fichiers du site sur disque tout seul.
État initial : le graph tournait mais produisait **0 fichier** (findings=0, ÉCHEC).

## Cause racine (confirmée)
`dynamic_agent_node` génère du **texte** (`agent_output`) et ne l'écrit **jamais**
sur disque. OpenHands (censé builder) est `status:planned` → no-op. Donc aucun
livrable, quel que soit le run.

## Corrections appliquées (`00_CORE/forge_agents/agent_nodes.py`)
1. **Deliverable bridge** : `_extract_target_dir(task)` (déduit le dossier cible
   depuis la task) + `_write_deliverables(output, dir)` qui parse la sortie et écrit
   les fichiers. Câblé dans `dynamic_agent_node` (branche `_is_build_task`).
2. **Système build dédié** : pour une tâche de code, on remplace le prompt NMP
   bruyant par un system-prompt « développeur web, fichier(s) complets, pas de NMP ».
3. **Budget tokens build** : 1500 → 8000/12000.
4. **Parseur multi-format** (deepseek change de protocole à chaque run) :
   `COMMAND|<verbe>|path|content` (write/WRITE_FILE/create/file…), `=== FILE: ===`,
   fences ```lang```, et fallback HTML brut. Testé unitairement (3/3 fichiers).

## Résultat
✅ La Forge **écrit désormais un `index.html` réel sur disque en autonome**
   (prouvé sur plusieurs runs : le fichier apparaît dans `site_B_forge_live/`).
   Le blocage fondamental « texte jamais écrit » est **levé**.

## Plafond restant (environnemental, PAS le pipeline)
❌ Site **complet** non garanti. Cause : **aucune `ANTHROPIC_API_KEY` dans `.env`**
   (et `GROQ_API_KEY` vide). Le tier HAIKU/Claude « prévu mais jamais appelé » →
   tout demote sur **ds2api-deepseek**, seul backend fonctionnel, qui :
   - tronque sa sortie à ~1k tokens → `index.html` coupé en plein `<style>` (pas de `</html>`) ;
   - varie son protocole à chaque run (`COMMAND|write|`, `COMMAND|file|write|`, HTML brut…),
     fragilisant tout parseur.
   Une boucle de continuation maison a été testée → ne converge pas (chaque
   continuation retronque). Retirée (ponytail : complexité sans résultat).

## ✅ RÉSOLU — OpenHands branché (2026-07-18)

Option 2 déployée : OpenHands est maintenant LE développeur de la Forge.

Déploiement réalisé :
- Images : `ghcr.io/all-hands-ai/openhands:0.54` (app, headless `core.main`)
  + `ghcr.io/all-hands-ai/runtime:0.54-nikolaik` (sandbox).
- `.env` : bloc `OPENHANDS_CMD` (docker + docker.sock + SANDBOX_VOLUMES) +
  `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` → **MiMo** `openai/mimo-v2.5-pro` (OpenAI-compat).
- `tools/dev/openhands.py` : fallback .env (le process forge ne charge pas dotenv) +
  `_engine_path()` (traduction `C:\...` → `/run/desktop/mnt/host/c/...` pour que le
  daemon Docker Desktop/WSL2 monte le workspace dans le runtime container).
- `agent_nodes.py` : `_oh_build(task, ctx, workspace=_extract_target_dir(task))`.

Pièges rencontrés (dans l'ordre) :
1. Image `docker.openhands.dev/...:latest` = build GUI, plus de module headless → passer à 0.54 ghcr.
2. `RUNTIME=local` de 0.54 buggé en conteneur (`BashSession '_closed'`) → runtime docker sandbox.
3. `SANDBOX_VOLUMES` refuse les chemins Windows (`C:` casse le split) → `_engine_path()`.
4. L'agent recrée le chemin relatif de la task dans son cwd → dossier imbriqué à aplatir
   (améliorable : dire « écris dans le répertoire courant » dans la task).

Résultat final (run `cafe_bastoche_oh1`) :
- **Site COMPLET livré en autonome** : index.html 16 Ko (balise `</html>` présente),
  style.css 17 Ko, app.js 10,5 Ko — 6 sections, Leaflet+CartoDB opérationnel (4 tuiles),
  0 erreur console, placeholders `[PRIX À CONFIRMER]` respectés (anti-hallucination).
- L'agent a même pris des screenshots navigateur pour se vérifier (.browser_screenshots).
- Coût LLM : MiMo (round-up 1K) — pas de clé Anthropic requise.

## Bugs Forge corrigés au passage (modules V6 untracked)
- `openviking.py` : `_Viking.get_findings_context()` manquant.
- `forge_graph.py` : `import threading` manquant.
- `auto_complexification.py` : `CavemanMsg(...)` appelé comme constructeur (= str).
