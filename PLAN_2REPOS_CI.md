# Forge sur 2 machines, 2 repos, 1 CI

État actuel : `git remote -v` est **vide**. La Forge n'existe que sur ce PC. Rien à cloner sur le portable tant que ce point n'est pas réglé.

## Architecture

```
repo A : forge-core        (le moteur — ce dossier)
repo B : forge-projects    (les produits livrés — ce que la Forge fabrique)

lien : B installe A via pip depuis un tag git. PAS de submodule.
```

Pourquoi pas de submodule : un submodule casse dès qu'une machine oublie `--recursive`.
Tu as déjà 4 submodules cassés ici (G0DM0D3, L1B3RT4S, AsyncHerald, nexus).

`forge-projects/requirements.txt` :
```
forge-core @ git+https://github.com/Leviantan07/forge-core@v0.1.0
```

Bump du tag = mise à jour du moteur. Une ligne, réversible.

## Étape 1 — Rendre la Forge clonable (~30 min, sur CE PC)

```bash
git status --porcelain | wc -l          # combien de fichiers en vrac
```

1. `.gitignore` : `05_STATE/`, `08_LOGS/`, `*.log`, `.env` (l'état runtime ne se versionne pas)
2. Vérifier zéro secret : `git log -p --all -S "sk-" | head`
3. Supprimer les submodules morts : `git rm --cached G0DM0D3 L1B3RT4S AsyncHerald nexus`
4. `gh repo create Leviantan07/forge-core --private --source=. --push`
5. `git tag v0.1.0 && git push --tags`

## Étape 2 — Le portable (~20 min)

1. `git clone https://github.com/Leviantan07/forge-core`
2. `python -m venv venv && .\venv\Scripts\Activate.ps1 && pip install -e .`
3. `npm i -g @anthropic-ai/claude-code` puis `claude` → login abonnement
4. Copier `.env` **à la main** (jamais par git)
5. `npx gitnexus analyze` pour réindexer localement

## Étape 3 — Le vrai "travail en équipe" (async)

Les 2 repos ne se parlent pas par git. Ils se parlent par **GitHub Issues + Actions**.

| Qui | Fait quoi |
|-----|-----------|
| Toi (portable ou PC) | ouvres une Issue dans `forge-projects` |
| CI de `forge-projects` | lance la Forge sur l'issue, ouvre une PR |
| Toi | review la PR depuis n'importe quelle machine |
| CI de `forge-core` | à chaque tag, ping `forge-projects` (repository_dispatch) |

C'est ça, l'équipe async : la file d'attente est le bug tracker, pas ta mémoire.

## Étape 4 — CI minimale (~40 min)

`forge-core/.github/workflows/ci.yml` — sur push : `pytest` + `ruff`. Rien d'autre.

`forge-core/.github/workflows/release.yml` — sur tag `v*` :
```yaml
- run: gh api repos/Leviantan07/forge-projects/dispatches -f event_type=forge-updated
  env: { GH_TOKEN: "${{ secrets.DISPATCH_PAT }}" }
```

`forge-projects/.github/workflows/sync.yml` — sur `repository_dispatch: [forge-updated]` :
bump le tag dans requirements.txt, lance les tests, ouvre une PR.

Secret à créer : `DISPATCH_PAT` (PAT fine-grained, scope `contents:write` sur forge-projects uniquement).

## Étape 5 — La routine quotidienne

1. Matin : `git pull` sur les 2 repos (30 s)
2. `claude` dans forge-projects → tu bosses
3. Soir : `git push` + tag si le moteur a bougé
4. La CI fait le reste pendant la nuit

## Ce que j'ai volontairement sauté

- Monorepo (fusionnerait tes 2 contextes, tu perds l'isolation)
- Docker/Coolify (à ajouter quand tu déploieras vraiment un produit)
- Sync automatique PC↔portable hors git (git suffit)
