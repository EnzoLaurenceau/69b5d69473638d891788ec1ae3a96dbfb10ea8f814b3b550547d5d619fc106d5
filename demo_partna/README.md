# Démo Partna — Forge vs Agent naïf

Split-screen animé : **même tâche, deux fois** (agent naïf à gauche, la Forge à
droite). Compteurs live : tokens, temps, coût, taux d'hallucination. 3 tâches
tirées du site de Partna. Se termine sur le CTA « 72h ou tu ne me dois rien ».

## Fichiers
- `index.html` — la page animée (auto-suffisante, aucune dépendance externe).
- `bench_partna.py` — le harness qui produit les **vrais** chiffres.
- `results.json` / `results.js` — sortie du bench (injectée aussi dans index.html).

## Voir la démo maintenant
```powershell
cd demo_partna
python -m http.server 8791
# ouvrir http://localhost:8791/index.html
```
> Ouvrir le fichier en `file://` marche aussi mais certains navigateurs bloquent
> le JS local — préférer le serveur http.

## Rendre les chiffres RÉELS
```powershell
python bench_partna.py --live      # tokens/latence/hallucination MESURÉS
```
Le bandeau passe au vert « CHIFFRES MESURÉS » et index.html est réinjecté.

**Ce qui est mesuré vs projeté (honnête) :**
- **Mesuré 1×** sur un moteur constant (MiMo `mimo-2.5-pro`), identique côté naïf
  et côté Forge : `in`/`out` tokens, latence, hallucinations (détecteur validé,
  in-scope Wilson-lb 98 %, 0 FP). Le moteur est tenu constant → le delta
  naïf↔Forge isole *l'effet d'optimisation*, pas un changement de modèle.
- **Coût par LLM = projection** : ces mêmes tokens tarifés au prix public de
  chaque fournisseur (`PRICES` en haut du bench). Pas d'appel live sur OpenAI /
  Claude / DeepSeek (aucune clé de ces API dans l'env). Sélecteur de fournisseur
  + matrice 3 LLM × naïf/Forge dans la page.

**LangSmith** : chaque run (naïf ET Forge, pour les 3 tâches) est loggé dans le
projet `super-agent-forge` si `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` dans
`.env` — inputs (charge prompt), outputs (tokens/latence/hallucination/coût).
No-op silencieux sinon. Le bench imprime `LangSmith tracing: ACTIVE|off`.

**Changer les prix / fournisseurs** → `PRICES` dans `bench_partna.py`
(modèle + $/1M in/out), puis relancer `--live`.

## Rendre une vidéo MP4 (hyperframes)
La `<div id="stage">` porte déjà les attributs hyperframes
(`data-composition-id`, `data-width/height/fps`).
```bash
npx hyperframes init partna-demo     # Node 22+ et FFmpeg requis
# copier index.html comme composition, puis :
npx hyperframes preview              # aperçu navigateur
npx hyperframes render               # -> MP4 déterministe
```
> Note : les compteurs sont animés via requestAnimationFrame. Pour un rendu
> frame-accurate, brancher l'adaptateur GSAP/WAAPI de hyperframes sur la timeline
> (`play()` expose déjà une progression 0→1). Sinon, capture d'écran vidéo simple.

## Personnaliser
- 3 tâches, contexte, faits vérifiables → en haut de `bench_partna.py` (`TASKS`).
- Tarifs de référence → `PRICE` dans le bench.
- Pile d'optimisation affichée → `OPTS` dans `index.html`.
