# HANDOFF — E2-02 unicité sémantique du monde

> Suite de [`HANDOFF_E1_01.md`](HANDOFF_E1_01.md) · branche `master` · **déjà dans l'historique** (cf. §5)
> Plan de référence : [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md)

---

## 0. Ce qui a changé en une phrase

**Deux agents ne peuvent plus créer deux fois le même PNJ sans le dire.** La contrainte
vit dans `upsert()` — le seul chemin d'écriture du monde — donc elle vaut pour les 10
types, pas seulement les personnages.

---

## 1. Livré

| Fichier | Rôle | Taille |
|---|---|---|
| [`00_CORE/forge_agents/world_kg.py`](00_CORE/forge_agents/world_kg.py) | Identité sémantique dans le chemin d'écriture + migration de schéma | +265 l. |
| [`test_world_kg_identity.py`](test_world_kg_identity.py) | **30 tests, tous verts** | 187 l. |
| [`00_CORE/tools/security_audit.py`](00_CORE/tools/security_audit.py) | Clé `world_kg.py:370` → `:571` (site inchangé) | +3 l. |
| [`pytest.ini`](pytest.ini) · [`AGENTS.md`](00_CORE/forge_agents/AGENTS.md) | Enregistrement CI + contrat local | modifiés |

**Vérifications réellement passées** :
- `pytest test_world_kg_identity.py` → **30 passed** ;
- `pytest` (suite complète) → **275 passed**, aucune régression (les 33 tests d'E2-01 tiennent) ;
- sonde manuelle contre le vrai moteur Kùzu : refus du quasi-doublon, `allow_similar`,
  écriture par alias, refus d'alias volé, fusion d'alias — 6 comportements observés, pas déduits ;
- `security_audit.py --check` → `world_kg.py` de nouveau couvert (la porte reste rouge pour
  10 sites d'une **autre** lignée, cf. §4).

---

## 2. Les trois décisions d'archi à ne pas re-litiger

1. **La contrainte est DANS `upsert()`.** Une fonction d'aide `check_duplicate()` à côté
   aurait été contournée par le premier agent appelant `upsert` directement. Un garde
   optionnel ne garde rien.
2. **`forge_fingerprint` n'a PAS été utilisé**, malgré l'intitulé du ticket. C'est un cache
   d'appels LLM : `make_fingerprint(prompt, system, tier)` répond à « ai-je déjà payé cette
   requête ? », pas à « ces deux noms désignent-ils la même personne ? ». Un sha n'a pas de
   voisinage — deux noms proches donnent deux hash étrangers. L'y brancher aurait produit
   une garantie fausse. Aucune dépendance ajoutée : la similarité tient en stdlib.
3. **La ressemblance alerte, elle n'arbitre pas.** `resolve()` ne résout que sur clé exacte
   ou alias **déclaré**. Fusionner deux entités sur un score, sans que personne l'ait décidé,
   est pire que le doublon qu'on voulait éviter.

---

## 3. Surface d'API

```python
from forge_agents.world_kg import get_world_kg, DuplicateEntityError, similarity
kg = get_world_kg("urth")

kg.add_character("Severian", role="protagoniste", canon="canon")
kg.add_character("Severian le bourreau")            # → DuplicateEntityError
kg.add_character("Severian le bourreau", allow_similar=True)   # deux entités, assumé
kg.add_character("Thecla", aliases=["la chatelaine"])
kg.add_character("la chatelaine", role="noble")     # met à jour Thecla, ne crée rien

kg.resolve("Character", "la chatelaine")   # → clé de Thecla, ou None
kg.find_similar("Character", "Severian")   # → [{id, name, score}] triés
kg.aliases_of("Character", "Thecla")
```

Réglage : `FORGE_WORLD_SIMILARITY` (défaut 0.62). Un monde à PNJ nommés en série
(« Garde royal I/II ») monte le seuil plutôt que de multiplier les `allow_similar=True`.

---

## 4. Ce que la vérification a révélé

### 4.1 `_CONNECTIONS` n'évince jamais — et l'échec est illisible
Les 30 tests passaient **un par un** et échouaient **en série** sur un
`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9`. Cause réelle : le cache de
connexions par chemin (introduit par E2-01 pour corriger le verrou double-ouverture) ne
libère jamais ; au ~16ᵉ chemin, Kùzu refuse d'ouvrir, et son message d'erreur natif
(cp1252, accentué) est décodé en utf-8 par le binding — le vrai motif est **effacé** par
l'erreur de décodage. Corrigé côté test (`reset_world_kg()` en teardown autouse).
**Reste ouvert côté production** : un processus long qui ouvre beaucoup de mondes
accumulera des handles. Une politique d'éviction est un ticket à part.

### 4.2 L'indexation `fichier:ligne` de la porte sécurité a re-cassé, comme annoncé
Ajouter ~150 lignes à `world_kg.py` a déplacé un site revu de `:370` à `:571` et rouvert la
porte alors que **le code de ce site n'a pas changé d'un caractère**. C'est la fragilité
documentée en §4.1 du handoff précédent, vérifiée en conditions réelles cette fois. Le site
a été re-vérifié ligne à ligne avant d'être re-tamponné, pas déplacé mécaniquement.

### 4.3 L'ordre des contrôles dans `upsert` n'est pas cosmétique
La fixture `_kg()` de `test_world_kg.py` construit un `WorldKG` **non initialisé** et repose
sur le fait que la validation des propriétés tourne **sans Kùzu**. Placer le contrôle
d'unicité (qui interroge la base) avant la validation casse 4 tests d'E2-01. Validation
déterministe d'abord, I/O ensuite.

---

## 5. Points ouverts

### 5.1 E6-01 n'a toujours produit aucune mesure réelle
`coverage()` = **0 %** sur 5 tickets faits. Pour E2-02, le `claim()` de départ n'a jamais
été enregistré (l'appel a avorté sur une `KeyError` avant `bl.claim`), donc aucun
horodatage de début défendable n'existe. Inscrire la durée reconstituée *a posteriori*
(0,124 h mesurée depuis le premier artefact sur disque) aurait couvert la fin du ticket,
pas le ticket — le même chiffre plausible-mais-faux que celui retiré pour E6-01.
**Le prochain ticket doit commencer par `with task_run("<id>")`** — sinon E6-01 restera un
instrument qui n'a jamais servi.

### 5.2 Les deux portes CI restent rouges — dette d'une autre lignée
Injection : 10 sites non revus dans `graph_db.py` (6), `knowledge_curator.py` (1),
`full_graph_connect.py` (3). État : `full_graph_connect.py`, `living_graph_sync.py` non
classés. Vérifié : **aucun n'est de cette lignée**, et E2-02 n'a rien ajouté à la dette
(son propre site est de nouveau couvert). Une session concurrente travaille dans ce dépôt ;
corriger des lignes qu'elle édite en direct produirait un conflit, pas une porte verte.

### 5.3 Toujours à trancher depuis E2-01
Le sort de `04_GRAPHIFY/kuzu_world` (commité comme `kuzu_graph`, ou ignoré) — la question
« où vit la vérité du jeu ». Non tranché par défaut.

---

## 6. Prochaine action

**E2-04 (GDD vivant, 2 j)** ou **E2-06 (journal de décisions, 1 j)** — tous deux ne
dépendent que d'E2-01, et E2-06 est du câblage (table `DesignDecision` et arête
`DERIVED_FROM` existent déjà).

À faire **sous `with task_run(...)`** dès la première action, cf. §5.1.

**Toujours à ne pas enchaîner** : E1-03 (estimation apprenante) — 0 % de couverture, il
s'entraînerait sur rien.
