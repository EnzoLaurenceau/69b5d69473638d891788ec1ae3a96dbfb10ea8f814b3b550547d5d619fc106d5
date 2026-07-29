# HANDOFF — E2-04 GDD vivant, généré depuis le graphe

> Suite de [`HANDOFF_E2_06.md`](HANDOFF_E2_06.md) · branche `master`
> Plan de référence : [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md)

---

## 0. Ce qui a changé en une phrase

**Le monde se lit enfin comme un document** — et ce document dit ce qu'il ne sait
pas. E2-01 posait *ce qu'est* le monde, E2-06 *pourquoi* il est ainsi ; E2-04 les
rend ensemble, régénérables, diffables, et refuse d'écraser le travail d'un humain.

---

## 1. Livré

| Fichier | Rôle | Taille |
|---|---|---|
| [`00_CORE/forge_agents/world_gdd.py`](00_CORE/forge_agents/world_gdd.py) | GDD vivant (nouveau module) | 624 l. |
| [`test_world_gdd.py`](test_world_gdd.py) | **53 tests, tous verts** | 429 l. |
| [`pytest.ini`](pytest.ini) · [`AGENTS.md`](00_CORE/forge_agents/AGENTS.md) · [`state_ownership.py`](00_CORE/tools/state_ownership.py) | Porte CI, contrat local, régime d'état | 1 ligne ch. + 1 bloc |

**Vérifications réellement passées** :
- `pytest` (suite complète) → **359 passed** (306 avant), aucune régression — après
  correction d'un refus réel de `test_state_isolation.py`, cf. §4.5 ;
- `pytest test_world_gdd.py` → **53 passed** ;
- **test de mutation** : 5 régressions injectées **en mémoire** (aucun fichier du
  dépôt modifié — cf. §4.4, la méthode précédente s'est retournée contre elle-même),
  **5 tuées** : 4, 4, 20, 2, 2 tests. La suite mord ;
- sonde manuelle contre le vrai moteur Kùzu : monde réaliste rendu, document relu ;
- `security_audit.py --check` → **PORTE OK** (14 HIGH, 14 revus — inchangé) ;
- `state_ownership.py --check` → **PORTE ÉCHEC** sur les 2 fichiers connus, `world_gdd`
  classé `tenant` et compté migré (33/33). Cf. §5.3 d'E2-06 : la porte reste rouge
  volontairement, ce ticket ne l'aggrave pas.

**Mesuré** (E6-01, depuis la PRISE réelle et non depuis le bloc `with`) :
**0,58 j pour 2,0 j estimés, −71 %**. La couverture de mesure du backlog passe de
**16,7 % à 28,6 %** (2/7 tâches faites mesurées). Restent non mesurées : E1-01,
E1-02, E2-01, E2-02, E6-01 — faites avant que `claimed_start()` n'existe, et il
n'y a aucun horodatage à reconstruire pour elles. La réserve de §5.1 d'E2-06 tient
toujours : ce chiffre mesure une **session d'agent**, pas un jour-homme, et E1-03
ne doit pas apprendre dessus sans trancher d'abord ce que `effort_days` signifie.

---

## 2. Les trois décisions d'archi à ne pas re-litiger

1. **Zéro octet d'ontologie touché — encore.** `_SECTIONS` ne déclare aucun type,
   il les RANGE. Un GDD qui aurait eu besoin d'un nœud « Pitch » ou « Système »
   aurait débordé de son ticket ; ces nœuds n'existent pas, donc le document ne
   prétend pas les rendre.
2. **L'exhaustivité des sections est un invariant, pas une convention.** Un test
   exige que chaque label de `WORLD_NODE_TABLES` soit rangé dans exactement une
   section. Sans lui, un 11ᵉ type ajouté à E2-01 disparaîtrait du GDD **en
   silence** — et un document ne dit jamais ce qu'il ne contient pas, donc
   personne ne le verrait. C'est le seul endroit du ticket où une omission serait
   invisible ; c'est donc le seul qui méritait un verrou.
3. **Le document est DÉTERMINISTE.** Aucun horodatage dans le corps : deux
   générations d'un monde inchangé produisent les mêmes octets. C'est ce qui rend
   le diff lisible — sans quoi « qu'est-ce qui a bougé dans le monde depuis la
   dernière session ? » se noie dans le bruit, et c'est exactement la question
   que l'objectif S2 pose.

---

## 3. Surface d'API

```python
from forge_agents.world_gdd import get_gdd, HandEditedGDDError
g = get_gdd("urth")

g.render()          # le GDD en markdown (vue pure, déterministe)
g.build()           # les mêmes données, sans mise en forme
g.gaps()            # les trous, nommément
g.write()           # → forge_store.state_path(f"gdd_{world}.md")
g.write(path, force=True)   # assume la perte d'une retouche humaine
```

`render(data)` accepte un `build()` déjà pris : on peut re-rendre sans
réinterroger le graphe, et vérifier ce que le document DIT du monde sans dépendre
de sa mise en page.

---

## 4. Ce que la vérification a révélé

### 4.1 Le premier jet marquait 11 entités sur 13 — donc n'en marquait aucune
Le module signalait les `draft`. Sondé sur un monde réaliste : **11 badges
⟨brouillon⟩ sur 13 entités**, parce que `draft` est la valeur PAR DÉFAUT
d'`upsert()` — personne ne l'a choisie. Un marqueur que presque tout le monde
porte n'informe pas : il apprend au lecteur à l'ignorer, donc à rater le vrai
brouillon isolé au milieu d'un chapitre arrêté.

Corrigé en inversant : **on signale `validated`** (l'acte délibéré), le brouillon
est l'état non marqué, et l'en-tête en donne la part — `2/13 validée(s)`. C'est la
même information, mais elle porte.

### 4.2 `gaps()` réclamait un résumé à une décision entièrement documentée
Le premier jet demandait un `summary` à tous les types. Résultat observé :
`perma-mort` — question, choix, rationale et alternatives renseignés — apparaissait
dans les trous comme « sans résumé ». Idem pour une `LoreRule` dont l'énoncé était
écrit. **Un faux positif dans une liste de trous est pire qu'un trou manquant** :
il apprend à ne plus lire la liste.

La table `_SUBSTANCE` dit ce qui tient lieu de substance par type (`rationale` pour
une décision, `statement` pour une règle, `summary` par défaut). Les trous sont
passés de 12 à 9 sur le monde de sonde — les 3 disparus étaient tous faux.

### 4.3 Trois pièges du moteur, sondés et non déduits
- **Une propriété non fournie revient à `None`, pas à `""`.** Tout le rendu passe
  donc par `_text()` ; un seul site d'affichage qui l'oublie met « None » dans un
  document livré.
- **`chrono` absent + `sorted()` = `TypeError`.** Un seul événement mal saisi
  aurait emporté le document ENTIER. La mutation le confirme brutalement : rétablir
  le tri naïf fait tomber **20 tests sur 53**. Les événements sans rang sont rangés
  en fin ET signalés comme trou.
- **`all_nodes(limit)` tronque en silence** (vérifié : `limit=2` sur 3 entités en
  rend 2, sans un mot). Un label qui rend autant de lignes que la limite est
  déclaré tronqué dans l'en-tête et dans les trous.

### 4.4 Le test de mutation a laissé le module mutaté sur le disque
La première méthode éditait `world_gdd.py` en place (sauvegarde, mutation, tests,
restauration). Le script a été interrompu **entre la mutation et la restauration** :
le module est resté avec `visible()` renvoyant `True`, et la campagne suivante a
tourné sur une référence à 4 échecs — que le verdict, bâti sur le seul code de
sortie de pytest, a lu comme « mutation tuée ». **Deux fautes qui se masquaient :**
un banc d'essai qui modifie son sujet, et un verdict qui ne compare rien.

Refait autrement : les mutations sont injectées **en mémoire** (`wg.visible = …`)
dans un sous-processus par mutation, aucun fichier du dépôt n'est touché, et le
verdict compare le nombre d'échecs à celui de la référence — laquelle est vérifiée
verte avant de conclure quoi que ce soit. Le banc est dans le scratchpad, pas dans
le dépôt : il n'a pas vocation à être rejoué en CI.

### 4.5 La suite COMPLÈTE a refusé le module, et elle avait raison
`pytest test_world_gdd.py` était vert ; la suite entière ne l'était pas.
`test_state_isolation.py::test_aucun_module_migre_n_est_casse_en_mode_script`
interdit à un module doté d'un bloc `__main__` d'importer `state_path` par un
import relatif NU — régression réelle de la migration W5-03a, où une porte de CI
lançait un module en script et se prenait « attempted relative import with no
known parent package ».

Le premier jet rendait cet import paresseux (dans `default_path()`), pour ne pas
tirer `forge_store` chez les appelants qui ne veulent que `render()`. Bénéfice
marginal, contre une convention que six modules migrés respectent déjà et qu'un
test verrouille. **Corrigé dans le sens de la convention, pas du contournement** :
import en tête, gardé par `try/except ImportError`, identique aux autres. Ne pas
« améliorer » ce test pour accueillir un futur module — c'est un cliquet.

Leçon transposable : `pytest <mon_fichier>.py` vert ne dit rien des invariants
transverses du dépôt. La suite complète fait partie du ticket, pas de sa relecture.

### 4.6 `write()` refuse d'écraser une retouche humaine
Le fichier porte un `<!-- gdd-lock sha256:… -->` = hash de son propre corps. Si le
corps sur disque ne correspond plus, `HandEditedGDDError` — **rien n'est écrit**.
Un fichier sans verrou (donc écrit par quelqu'un d'autre) est traité de la même
façon : on ne présume jamais qu'un fichier qu'on n'a pas écrit est jetable.

Ce n'est pas de la prudence décorative. Perdre UNE fois le travail d'un humain
suffit à ce que plus personne ne régénère le document — et un GDD qu'on ne
régénère plus est mort, ce qui est précisément l'échec que le ticket doit éviter.
Le hash normalise les fins de ligne : sans ça, un aller-retour par git
(`core.autocrlf`) crierait « édité à la main » sur un fichier intact.

---

## 5. Points ouverts

### 5.1 Le taux de traçabilité est le vrai chiffre du ticket, et il est bas
L'en-tête affiche `N/M rattachée(s) à une décision de design`. Sur le monde de
sonde : **18,2 %**. Ce n'est pas un défaut du module — c'est la mesure honnête de
ce que le monde sait de lui-même. À surveiller quand un vrai monde sera peuplé :
un GDD dont 90 % des entités n'ont aucun « pourquoi » signale que les décisions
se prennent hors du graphe, donc se re-litigeront à la session suivante.

### 5.2 Le module n'a jamais rendu un VRAI monde — il n'en existe aucun
Vérifié en fin de ticket : `04_GRAPHIFY/kuzu_world` existe mais le monde `default`
y est **entièrement vide** (0 nœud sur les 10 tables). Tout ce qui a été rendu
l'a été contre des mondes de sonde construits pour l'occasion. Le module est donc
vérifié, pas *éprouvé* : il faudra le relire le jour où un monde réel le remplira,
notamment sur le volume (le rendu fait deux passes de `all_nodes` par label — une
pour `build()`, une pour `gaps()`) et sur la limite par défaut de 500.

C'est aussi une donnée pour E2-03 et E7-* : ils écriront dans un graphe vierge.
Et ça recoupe le point ouvert « où vit la vérité du jeu » (§5.4).

### 5.3 Le GDD ne rend pas ce que l'ontologie ne porte pas
Pas de pitch, pas de boucle de gameplay, pas de systèmes chiffrés : ces nœuds
n'existent pas en E2-01. **Ne pas les inventer dans le renderer** — un GDD qui
fabrique des sections que le graphe ne sait pas remplir est exactement le
« document d'apparence complète » que ce ticket refuse. Si le besoin est réel,
c'est un ticket d'ontologie (E2-01 bis), pas une rustine ici.

### 5.4 `canon` est affiché, pas gardé
Chaque entité dont le `canon` n'est pas `generated` porte sa provenance dans le
document. C'est le minimum pour qu'E2-03 (ingestion du Livre du Nouveau Soleil)
puisse trancher plus tard ce qui est inspiration et ce qui serait copie — mais
**ce module ne fait aucun gate copyright**, et il ne faut pas le lire comme tel.
Le gate est dans E3-07.

### 5.5 Toujours ouverts depuis E2-01/E2-02/E2-06
- `_CONNECTIONS` n'évince toujours jamais (les tests s'en protègent en teardown) ;
- porte état rouge sur `full_graph_connect.py` / `living_graph_sync.py` — ticket
  séparé, cf. §5.3 d'E2-06 : tamponner `exempt` blanchirait une fuite potentielle ;
- `actual_tokens` reste structurellement à 0 en session d'agent (§5.2 d'E2-06) ;
- le sort de `04_GRAPHIFY/kuzu_world` — « où vit la vérité du jeu » — non tranché (cf. §5.2).

---

## 6. Prochaine action

**E2-05 (brancher le RAG + re-ranking sur le World-KG, 2 j)** — c'est le dernier
ticket E2 qui change le COMPORTEMENT de la Forge plutôt que sa documentation :
aujourd'hui le monde est peuplé et rendu, mais aucun agent ne le consulte avant
d'écrire. `context_pack()` est l'accroche déjà prévue, et le ticket se fait en
module à côté — zéro octet de `world_kg.py`, même patron qu'E2-06 et E2-04.

**À faire dès la première action** : `bl.claim("<id>", "<session>")`, puis clôture
sous `task_run(..., claim=False, started_at=claimed_start("<id>"))`.

**À ne PAS lancer en parallèle d'un ticket qui touche le monde** : E9-02 (gate
`CONTRADICTS` bloquant). Les tests d'E2-04 créent délibérément des arêtes
`CONTRADICTS` pour vérifier le rendu des trous ; un gate bloquant dans le chemin
d'écriture les casse, et on cherche longtemps lequel des deux tickets a tort.

**Toujours à ne pas enchaîner** : E1-03 (estimation apprenante) — cf. §5.1 d'E2-06,
il apprendrait sur deux unités incommensurables.
