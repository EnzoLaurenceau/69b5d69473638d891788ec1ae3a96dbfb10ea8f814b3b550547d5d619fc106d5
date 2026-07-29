# HANDOFF — E6-02 score qualité normalisé 0-100 par type d'artefact

> Suite de [`HANDOFF_E2_04.md`](HANDOFF_E2_04.md) · branche `master`
> (chaîne : E1-01 → E2-02 → E2-06 → E2-04 → **E6-02**)
> Plan de référence : [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md)

---

## 0. Ce qui a changé en une phrase

**La Forge sait enfin dire « je n'ai pas mesuré » au lieu de dire 100.** Le seul
chiffre de qualité qui existait — celui du Harness — valait 100 pour à peu près
n'importe quoi, PNG compris ; il y a désormais une note par artefact qui
distingue *réussi* de *non mesuré*, et E6-01 a son premier `quality` rempli.

---

## 1. Livré

| Fichier | Rôle | Taille |
|---|---|---|
| [`00_CORE/forge_agents/artifact_quality.py`](00_CORE/forge_agents/artifact_quality.py) | Le scoreur (nouveau module) | ~700 l. |
| [`test_artifact_quality.py`](test_artifact_quality.py) | **37 tests, tous verts** | ~430 l. |
| [`00_CORE/forge_agents/harness_engine.py`](00_CORE/forge_agents/harness_engine.py) | 3 correctifs (cf. §3) | +25 l. |
| [`00_CORE/forge_agents/forge_task_ledger.py`](00_CORE/forge_agents/forge_task_ledger.py) | Branchement `autoscore=True` | +30 l. |
| [`pytest.ini`](pytest.ini) · [`AGENTS.md`](00_CORE/forge_agents/AGENTS.md) | Enregistrement CI + contrat local | modifiés |

**Vérifications réellement passées** :
- `pytest` (suite complète) → **395 passed**, aucune régression (359 avant) ;
- **test de mutation** : 3 régressions injectées volontairement — plafond retiré,
  critère non mesuré compté comme réussi, répartiteur Harness re-cassé — tuent
  respectivement **2, 6 et 1** tests, puis fichiers restaurés verts. La suite mord ;
- dogfooding : le ticket a été clos **par le module lui-même** —
  `task_run(autoscore=True)` sur les 7 artefacts déclarés → **premier `quality`
  jamais enregistré dans le ledger : 65,8** (code 74,2 · narratif 49,0 · 1 non
  noté), durée mesurée **0,044 j**, et `coverage()` passe de **16,7 % à 37,5 %**.
  Ce 65,8 a été relevé **avant** le correctif §4.4 : il est légèrement
  pessimiste sur les deux artefacts narratifs. Il n'a pas été « rejoué » —
  ré-ouvrir un `task_run` ajouterait un second événement et l'agrégat moyennerait
  deux mesures prises sous deux barèmes.

```python
from forge_agents.artifact_quality import score_artifact, score_artifacts

q = score_artifact("00_CORE/forge_agents/world_kg.py")
q.score, q.grade, q.confidence      # 77.3, 'B', 0.89
print(q.render())                    # le détail, critère par critère

score_artifacts(["hero.png", "theme.wav"], world_id="urth")
```

Et branché sur E6-01 — c'est ce qui remplit le champ resté vide depuis :

```python
with task_run("E6-02", claim=False, started_at=claimed_start("E6-02"),
              autoscore=True) as run:
    run.artifact("00_CORE/forge_agents/artifact_quality.py")
```

---

## 2. Comment la note est construite

```
score = 100 × Σ(poids × valeur) / Σ(poids)      sur les seuls critères MESURÉS
confidence = Σ(poids mesurés) / Σ(poids déclarés)
```

Quatre types, quatre jeux de sondes — **toutes déterministes et gratuites**
(aucun appel LLM : une note payante ne serait ni reproductible ni comparable
d'une exécution à l'autre) :

| Type | Sondes |
|---|---|
| `code` | syntaxe (AST) · secrets · slop · gestion d'erreur · `print()` · tests existants · **proportion** de docstrings · **proportion** d'annotations · lint |
| `asset` | lisible (Pillow) · non uniforme · dimensions · alpha · octets/pixel · en-tête magique |
| `audio` | lisible (`wave`) · non silencieux · saturation · durée · fréquence · offset continu · en-tête |
| `narrative` | substance · gabarits résiduels · répétitions · structure · tics de style · **ancrage World-KG** |

Trois règles fixent la lecture du chiffre :

1. **Un critère non mesuré n'est jamais un critère réussi** — il vaut `None`,
   sort du dénominateur, et fait baisser `confidence`. Renormaliser sur le seul
   mesuré est ce qui rend les quatre types comparables ;
2. **aucun critère mesuré → `score is None`, `grade == "?"`** — jamais 0, jamais
   100. `?` dit « pas mesuré », `F` dit « mauvais » : les confondre fait jeter un
   livrable correct qu'on n'a pas su ausculter ;
3. **un critère `BLOCKING` à 0 plafonne le score à 49** (juste sous le plancher
   du C, aligné sur la porte de livraison Herald). Voir §4.1 : c'est un WAV
   silencieux noté **B** qui a imposé cette règle.

---

## 3. Ce que la sonde a trouvé — et qui a dicté l'architecture

`HarnessEngine.validate(CODE, …)` a été exécuté contre un vrai fichier **avant**
d'écrire une ligne. Ce qu'il renvoyait :

```
CODE score: 100.0   passed: True
   syntax_check          passed=True :: 1 files compile OK
   lint_flake8           passed=True :: flake8 clean          ← flake8 ABSENT
   type_hints            passed=True :: No implementation (passed by default)
   docstrings            passed=True :: No implementation (passed by default)
   tests_exist           passed=True :: No implementation (passed by default)
   no_hardcoded_secrets  passed=True :: No implementation (passed by default)
   no_print_statements   passed=True :: No implementation (passed by default)
   error_handling        passed=True :: No implementation (passed by default)
   imports_sorted        passed=True :: isort check (placeholder)
   no_ai_slop            passed=True :: No implementation (passed by default)
```

Un **PNG** validé comme du CODE : **100**. Un type sans gate (`DOCUMENT`) :
**100 avec zéro gate exécutée**. Quatre causes distinctes, toutes constatées :

### 3.1 Huit gates sur dix ne s'exécutaient jamais — **corrigé**
Les gates déclarent `check="check_no_secrets"` ; `_run_gate` cherchait le seul
`_check_{gate.check}` → `_check_check_no_secrets`, inexistant. Et une gate sans
implémentation **vaut succès par défaut**. Les trois gates `critical` (secrets,
slop) en faisaient partie. Correctif : les deux formes sont tentées.

### 3.2 « flake8 clean » sans flake8 — **corrigé**
`python -m flake8` absent sort en code ≠ 0 avec une sortie **vide**, que le
comptage lisait comme « 0 erreur ». Un outil manquant ne décerne plus de succès.

### 3.3 `HarnessResult.grade` n'existait pas — **corrigé**
`agent_nodes.py` (post-mortem) lisait `_hr.grade` sur un objet qui ne l'exposait
pas : l'`AttributeError` partait dans un `except Exception` et le grade n'était
**jamais** affiché. `grade` est désormais une propriété, sur la même échelle A-F
que le score par artefact — un seul barème dans la Forge.

### 3.4 Un lot sans `.py` passe toutes les gates CODE — **NON corrigé, et assumé**
Toutes les gates CODE filtrent `.py` : sur un lot qui n'en contient aucun,
chacune « réussit » sans avoir rien regardé, et le PNG ressort toujours à 100.
Le corriger demande de faire refuser à `validate()` un lot étranger à son type —
mécanisme nouveau dans un module qui n'est pas celui de ce ticket, et régression
possible pour `forge_graph` (qui lui passe des `artifact_files` de tout type).
**Un test nomme ce trou** (`test_le_png_note_comme_du_code_reste_un_trou_du_harness`)
et tombera le jour où quelqu'un le bouchera. Ce qu'E6-02 garantit sur ce cas,
c'est le **classement** — un PNG est un `asset`, jamais du code.

---

## 4. Ce que la vérification a révélé dans le module lui-même

### 4.1 Une pondération correcte donnait un **B à un fichier inutilisable**
Un WAV entièrement silencieux : lisible, durée saine, 44,1 kHz, aucune
saturation, aucun offset, en-tête conforme — **toutes ses sondes sauf une disent
« bon »**. Score : **76,9/100, grade B**. Le chiffre était mathématiquement juste
et pratiquement mensonger. D'où `CAP_BLOCKED` : certains défauts ne se
compensent pas. Le plafond ne touche que les sondes qui signifient
« l'artefact ne peut pas servir » (`syntax`, `readable`, `not_blank`,
`not_silent`, `container`, `no_placeholder`) — **pas** `no_secrets`/`no_slop`,
qui sont des fautes graves déjà sanctionnées par leur poids.

### 4.2 Le contenu d'un fichier pouvait se faire passer pour une sonde muette
Le détail d'un échec Harness **cite le texte trouvé dans le fichier** : « AI slop
detected: `'placeholder'` ». Or ce module reconnaissait les sondes muettes en
cherchant « placeholder » **par sous-chaîne** — une vraie détection devenait donc
« sonde indisponible », c'est-à-dire critère non mesuré, c'est-à-dire **note plus
haute**. Exactement le mensonge que le module existe pour empêcher, trouvé en le
faisant tourner sur son propre fichier de tests. Reconnaissance désormais par
**égalité exacte** (`_MUTE_EXACT`), verrouillée par un test.

### 4.3 Deux critères ne pouvaient pas être délégués
Le Harness bascule à seuil fixe (« >10 manquants ») : sur un gros fichier le
seuil est franchi d'office, sur un petit jamais. Un seuil ne normalise pas —
`docstrings` et `type_hints` sont donc des **proportions**, mesurées par AST.
Même raison pour `tests_exist` : le Harness ne cherche que dans le dossier du
fichier, or les tests de cette Forge vivent à la **racine** — le critère
répondait « absent » à tous les coups. Un critère qui répond toujours la même
chose ne mesure rien.

### 4.4 Un critère `blocking` doit être PRÉCIS, pas seulement large
Premier jet du motif « gabarit résiduel » : `\bTODO\b`, `\bplaceholder\b` nus.
Résultat mesuré à la clôture du ticket : **le `AGENTS.md` et ce handoff même
tombaient à 49 (D)** parce qu'ils *parlent* de ces marqueurs. Un critère qui
plafonne la note ne peut pas se permettre cette imprécision. Le motif exige
désormais un marqueur **en position** (`TODO:`, `<placeholder>`, `[à compléter]`,
`lorem ipsum`), pas un mot en prose — un « TODO: écrire la quête » reste attrapé,
et un test le verrouille. Il reste un tail assumé : un document qui **cite**
littéralement `TODO:` comme exemple (c'est le cas du `AGENTS.md`, section
Anti-Slop) est signalé. Le détail nomme les marqueurs trouvés ; la note se
conteste en un coup d'œil.

### 4.5 La syntaxe est vérifiée par `ast.parse`, pas par le sous-processus
Le Harness lance `python -m py_compile` : le `python` du PATH n'est pas
l'interpréteur du projet (constat du handoff E2-06 §4.4), et son absence ferait
**échouer** une gate critique sur un fichier parfaitement valide. `ast.parse`
sert en plus aux deux critères ci-dessus — une seule analyse pour trois sondes.

---

## 5. Points ouverts

### 5.1 `grounded` ne se mesure pas sans monde, et c'est voulu
L'ancrage narratif résout les noms propres du texte contre le World-KG d'E2-01 —
le seul critère qui distingue un texte de jeu d'un texte bien écrit, un PNJ
inventé en cours de rédaction étant indétectable au style. Il reste **NON
mesuré** tant qu'aucun `world_id` n'est passé : sans monde de référence,
sanctionner un nom propre revient à noter au hasard. Conséquence pratique :
`task_run(autoscore=True)` sur des artefacts narratifs de jeu doit passer
`world_id=…`, sinon la confiance plafonne vers 0,77 sur ce type.

### 5.2 Le rubric est uniforme, et il coûte au fichier de tests
`test_artifact_quality.py` sort à **50,5/100 (C)** : il contient un mot de passe
factice (`no_secrets` = 0) et le mot « placeholder » (`no_slop` = 0) — les deux
sont **délibérés**, ce sont les chaînes qui testent les détecteurs eux-mêmes.
Aucune exemption n'a été ajoutée : s'auto-exempter est précisément ce que ce
module refuse de faire ailleurs. À savoir avant de lire les notes d'E6-03 : un
fichier de tests de détecteurs sera toujours pénalisé par ses propres fixtures,
et un document qui **cite** un marqueur de gabarit (le `AGENTS.md`, section
Anti-Slop : `# TODO: implement`, « lorem ipsum ») sort à **49 (D)**. Dans les
deux cas le détail nomme la chaîne trouvée — la note est contestable en un coup
d'œil, ce qui vaut mieux qu'une exemption invisible.

### 5.3 `lint` reste non mesuré partout
Ni `ruff` ni `flake8` ne sont installés dans cet environnement : le critère
(poids 2, `high`) sort NON mesuré sur **tout** fichier Python, ce qui plafonne la
confiance du type `code` à 0,89. `pip install ruff` le rend mesurable sans
toucher au code — le critère est déjà écrit et gradué par densité d'alertes.

### 5.4 `actual_tokens` reste à 0 (inchangé depuis E2-06 §5.2)
Le raisonnement de cette session tourne sur l'abonnement Claude et ne passe pas
par `forge_metrics.record()`. La durée et désormais la **qualité** sont mesurées,
le coût ne l'est pas. À connaître avant de bâtir E6-03 (dashboard) dessus : la
colonne « artefacts les plus chers » sera vide pour tout ticket fait en session
d'agent, tandis que la colonne qualité, elle, sera pleine.

### 5.5 Toujours ouverts depuis E2-01/E2-02/E2-06
- `full_graph_connect.py` / `living_graph_sync.py` non classés (porte état rouge,
  et **c'est plus honnête** que de tamponner `exempt` — cf. E2-06 §5.3) ;
- `_CONNECTIONS` n'évince toujours jamais ;
- le sort de `04_GRAPHIFY/kuzu_world` non tranché.

### 5.6 Porte état : ÉCHEC, et il est hérité
`state_ownership --check` sort **rouge** — mais uniquement sur les deux fichiers
laissés non classés par E2-06 §5.3 (`full_graph_connect.py`,
`living_graph_sync.py`), délibérément, parce que les tamponner `exempt`
blanchirait une fuite inter-clients potentielle en coche verte. **Ce ticket n'y
ajoute rien** : `artifact_quality.py` n'écrit aucun état. Les trois autres portes
sont vertes (`pytest` 455 · `security_audit` OK, 14 HIGH tous revus ·
compilation OK).

---

## 6. Prochaine action

**E6-04 (alerte de dérive budget, 1 j)** — ne dépend que d'E6-01, tout petit, et
`mimo_budget` + `epic_costs()` fournissent déjà la matière.

**E6-03 (dashboard) est prêt côté qualité mais pas côté coût** : lire §5.4 avant
de le commencer, sinon la moitié des colonnes affichera 0 sans que ce zéro dise
« non mesuré ».

**À faire dès la première action de tout ticket** : `bl.claim("<id>", "<session>")`,
puis clôture sous `task_run(..., claim=False, started_at=claimed_start("<id>"),
autoscore=True)`. C'est ce qui remplit à la fois la durée (E6-01) et la qualité
(E6-02).

**Toujours à ne pas enchaîner** : E1-03 (estimation apprenante) — cf. E2-06 §5.1,
`effort_days` (estimation humaine) et `actual_days` (session d'agent) ne sont
toujours pas commensurables.
