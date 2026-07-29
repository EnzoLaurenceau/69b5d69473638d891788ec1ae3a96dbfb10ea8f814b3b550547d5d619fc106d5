"""
world_kg.py — World Knowledge Graph (ontologie du MONDE, pas du code)
=====================================================================
E2-01 du plan RPG (cf. 07_REPORTS/AUDIT_APTITUDE_RPG.md §3, epic WORLD-KG).

Pourquoi un module séparé et pas une extension de `graph_db.py` :
  `graph_db.py` indexe la Forge elle-même (Agent/Project/Concept/Repository/…).
  Il est EN PRODUCTION : la neural map de la console lit ce graphe via
  `09_WEB/inference_api.py::_GRAPH_LABELS`, et `knowledge_curator` /
  `service_map` / `security_audit` en dépendent. Ajouter `Character`/`Quest`
  à `NODE_TABLES` ferait remonter des PNJ dans la carte du code.
  → seconde ontologie, seconde base Kuzu, ZÉRO modification du graphe existant.
  Les fonctions de durcissement (`_esc`/`_label`/`_num`) sont en revanche
  IMPORTÉES de `graph_db` : une seule implémentation d'échappement, déjà
  verrouillée par `test_graph_db_escaping.py`. Ne pas la dupliquer.

Ce que ce module garantit (les seules promesses tenues ici) :
  - un schéma typé du monde : 10 tables de nœuds, 6 tables d'arêtes ;
  - une identité DÉTERMINISTE (`world_key`) → E2-02 peut y brancher
    l'unicité sémantique via `forge_fingerprint` sans changer le schéma ;
  - un cloisonnement par `world_id` : plusieurs jeux dans une même base ;
  - une whitelist de propriétés par label : écrire une propriété inconnue
    lève, elle n'est jamais avalée en silence ;
  - `context_pack()` : le voisinage d'une entité prêt à être injecté dans un
    prompt — c'est par là que tout agent interroge le monde AVANT d'écrire.

Ce qu'il ne fait PAS (tickets suivants, ne pas anticiper ici) :
  E2-02 unicité sémantique · E2-03 ingestion du canon · E2-04 GDD vivant ·
  E2-05 branchement RAG + re-ranking · E2-06 journal de décisions.

Usage:
    from forge_agents.world_kg import get_world_kg
    kg = get_world_kg(world_id="urth")
    kg.add_character("Severian", role="protagoniste", faction="Guilde")
    kg.add_location("Nessus", kind="city")
    kg.link("LOCATED_IN", "Character", "Severian", "Location", "Nessus")
    pack = kg.context_pack("Character", "Severian")
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

# Échappement/validation partagés — implémentation unique et durcie (W6-01).
from .graph_db import FORGE_ROOT, _esc, _label, _num

logger = logging.getLogger("WorldKG")

WORLD_DB_PATH = Path(os.environ.get(
    "FORGE_WORLD_KG_PATH", str(FORGE_ROOT / "04_GRAPHIFY" / "kuzu_world")
))

DEFAULT_WORLD_ID = os.environ.get("FORGE_WORLD_ID", "default")

# ── Vocabulaires fermés ──────────────────────────────────────────────────────
# `canon` tranche la question « d'où vient cette affirmation ». E9 (LORE-GUARD)
# et le gate copyright (E3-07) en dépendent : une contradiction avec du `canon`
# n'a pas le même poids qu'une contradiction avec du `generated`.
CANON_KINDS = ("canon", "derived", "generated", "human")
# `status` pilote ce qui entre dans le GDD (E2-04) et dans le build (E5).
STATUS_KINDS = ("draft", "validated", "cut")

# ── Ontologie du monde ───────────────────────────────────────────────────────
# Propriétés communes à TOUT nœud du monde. `id` est la clé primaire, calculée
# par `world_key()` — jamais fournie par l'appelant.
_COMMON_PROPS: dict[str, str] = {
    "id": "STRING",
    "world_id": "STRING",
    "name": "STRING",
    "summary": "STRING",
    "tags": "STRING",          # csv — Kuzu typé liste évité pour rester portable
    # E2-02 : autres noms sous lesquels CETTE entité est connue (« le bourreau »
    # pour Severian). Séparés par `|` — un alias peut contenir une virgule, pas
    # `tags`. C'est ce qui rend l'unicité sémantique DÉCLARATIVE : un agent qui
    # écrit un alias déjà pris met à jour l'entité existante au lieu d'en créer
    # une seconde.
    "aliases": "STRING",
    "canon": "STRING",
    "status": "STRING",
    "provenance": "STRING",    # agent/source ayant produit le nœud (E6 : traçabilité)
}

# Propriétés spécifiques par type. Cette table est la SOURCE DE VÉRITÉ : elle
# sert à la fois au DDL et à la validation des écritures. Ajouter une propriété
# ici suffit — ne jamais écrire de DDL en dur ailleurs.
_TYPE_PROPS: dict[str, dict[str, str]] = {
    "Character":      {"role": "STRING", "species": "STRING", "faction": "STRING",
                       "alignment": "STRING", "arc": "STRING", "appearance": "STRING",
                       "voice": "STRING", "alive": "BOOL"},
    "Faction":        {"ideology": "STRING", "seat": "STRING", "power": "DOUBLE",
                       "era": "STRING"},
    "Location":       {"kind": "STRING", "region": "STRING", "climate": "STRING",
                       "danger": "INT64", "biome": "STRING"},
    "Quest":          {"kind": "STRING", "act": "INT64", "giver": "STRING",
                       "objective": "STRING", "reward": "STRING", "outcome": "STRING"},
    "Item":           {"kind": "STRING", "rarity": "STRING", "effect": "STRING",
                       "value": "INT64", "unique": "BOOL"},
    "Ability":        {"kind": "STRING", "cost": "INT64", "cooldown": "INT64",
                       "effect": "STRING", "school": "STRING"},
    # `chrono` : rang absolu dans la chronologie interne du monde. C'est ce qui
    # rend une incohérence temporelle DÉTECTABLE (E9) — sans lui, « avant/après »
    # n'est qu'une phrase.
    "Event":          {"era": "STRING", "chrono": "INT64", "consequence": "STRING",
                       "scale": "STRING"},
    # `hard=True` = règle inviolable : sa violation bloque, elle n'avertit pas.
    "LoreRule":       {"statement": "STRING", "scope": "STRING", "hard": "BOOL",
                       "rationale": "STRING"},
    "DialogueNode":   {"speaker": "STRING", "text": "STRING", "condition": "STRING",
                       "emotion": "STRING", "next_ids": "STRING"},
    "DesignDecision": {"question": "STRING", "choice": "STRING", "rationale": "STRING",
                       "alternatives": "STRING", "decided_by": "STRING"},
}

WORLD_NODE_TABLES: tuple[str, ...] = tuple(_TYPE_PROPS)

# ── Arêtes ───────────────────────────────────────────────────────────────────
# Les 6 arêtes du ticket E2-01. Chaque arête déclare les couples autorisés :
# une arête hors couple lève, ce qui empêche un agent de fabriquer une relation
# qui n'a pas de sens (un Item ne « connaît » personne).
_ALL = WORLD_NODE_TABLES

WORLD_EDGE_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "KNOWS": (
        ("Character", "Character"), ("Character", "Faction"),
        ("Faction", "Faction"), ("Character", "Location"),
        ("Character", "Event"), ("Faction", "Event"),
    ),
    "OWNS": (
        ("Character", "Item"), ("Faction", "Item"), ("Faction", "Location"),
        ("Character", "Ability"), ("Character", "Location"),
    ),
    "LOCATED_IN": (
        ("Character", "Location"), ("Location", "Location"), ("Item", "Location"),
        ("Event", "Location"), ("Quest", "Location"), ("Faction", "Location"),
        ("DialogueNode", "Location"),
    ),
    "REQUIRES": (
        ("Quest", "Quest"), ("Quest", "Item"), ("Quest", "Character"),
        ("Quest", "Ability"), ("Ability", "Ability"), ("Ability", "Item"),
        ("DialogueNode", "Quest"), ("DialogueNode", "Item"),
        ("DialogueNode", "DialogueNode"), ("Item", "Ability"),
    ),
    # L'arête qui fait exister LORE-GUARD (E9) : une incohérence se STOCKE,
    # elle ne se contente pas d'apparaître dans un rapport.
    "CONTRADICTS": (
        ("LoreRule", "LoreRule"), ("LoreRule", "Event"), ("Event", "Event"),
        ("LoreRule", "Character"), ("LoreRule", "Quest"), ("Quest", "Quest"),
        ("LoreRule", "Item"), ("LoreRule", "Location"), ("Character", "Character"),
        ("DialogueNode", "LoreRule"),
    ),
    # Provenance/filiation : « ce contenu découle de ». Sert au gate copyright
    # (E3-07 : inspiration tracée, jamais copie) et à E2-06.
    "DERIVED_FROM": (
        tuple((lbl, "LoreRule") for lbl in _ALL)
        + tuple((lbl, "DesignDecision") for lbl in _ALL)
        + (("Character", "Character"), ("Location", "Location"),
           ("Quest", "Quest"), ("Item", "Item"), ("Event", "Event"),
           ("DialogueNode", "DialogueNode"))
    ),
}

WORLD_EDGE_TABLES: tuple[str, ...] = tuple(WORLD_EDGE_PAIRS)

_EDGE_PROPS = "weight DOUBLE DEFAULT 1.0, context STRING DEFAULT '', provenance STRING DEFAULT ''"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ── Identité ─────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """Nom lisible → fragment d'identifiant stable.

    Déterministe et sans dépendance : deux agents qui écrivent « Sévérian » et
    « Severian » produisent la MÊME clé. C'est le premier rempart contre le
    doublon ; le second (proximité sémantique, « le bourreau » vs « Severian »)
    est E2-02 et se branchera sur `forge_fingerprint`.
    """
    norm = unicodedata.normalize("NFKD", str(name))
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return _SLUG_RE.sub("-", norm.lower()).strip("-")


def world_key(world_id: str, label: str, name: str) -> str:
    """Clé primaire d'un nœud du monde : `{world_id}:{Label}:{slug}`.

    Kuzu n'accepte qu'une colonne en clé primaire : le cloisonnement par monde
    est donc encodé DANS la clé, pas à côté. Deux jeux peuvent coexister dans
    la même base sans qu'un `Severian` de l'un écrase celui de l'autre.
    """
    label = _label(label, WORLD_NODE_TABLES)
    slug = slugify(name)
    if not slug:
        raise ValueError(f"nom inexploitable pour une clé: {name!r}")
    return f"{slugify(world_id) or 'default'}:{label}:{slug}"


# ── E2-02 · Identité sémantique ──────────────────────────────────────────────
# Le rempart d'E2-01 (`world_key`) n'attrape que le doublon EXACT après
# normalisation : « Sévérian » et « Severian » convergent. Il ne voit pas
# « Severian » vs « Severian le bourreau » — deux clés, deux PNJ, un monde
# incohérent. C'est ce que ce bloc ferme.
#
# Pourquoi PAS `forge_fingerprint` (que l'audit suggérait) : ce module est un
# cache d'appels LLM (`make_fingerprint(prompt, system, tier)` → sha d'un
# prompt). Il répond à « ai-je déjà payé cette requête ? », pas à « ces deux
# noms désignent-ils la même personne ? ». Un sha n'a pas de voisinage : deux
# chaînes proches donnent deux hash étrangers. Le plier à cet usage aurait donné
# une fausse garantie. Seul `_sha` (utilitaire) reste partagé, via la même
# stdlib — aucune dépendance ajoutée.

#: Mots vides ignorés dans la comparaison de noms. Sans eux, « le Bourreau » et
#: « Bourreau » tombent à 0,5 de similarité et passent pour deux entités.
_NAME_STOPWORDS = frozenset((
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "da", "di",
    "the", "a", "an", "of", "der", "die", "das", "von", "van", "el",
))

#: Seuil au-delà duquel deux noms sont réputés désigner la même entité.
#: Réglable — un monde à PNJ nombreux et nommés en série (« Garde royal I/II »)
#: voudra monter le seuil plutôt que multiplier les `allow_similar=True`.
SIMILARITY_THRESHOLD = float(os.getenv("FORGE_WORLD_SIMILARITY", "0.62"))


class DuplicateEntityError(ValueError):
    """Écriture refusée : une entité trop proche existe déjà.

    Porte `candidates` (les entités en cause, triées par score décroissant) pour
    qu'un appelant automatique puisse décider — fusionner, aliaser, ou assumer.
    """

    def __init__(self, message: str, candidates: list[dict] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


def name_tokens(name: str) -> frozenset[str]:
    """Nom → jeu de tokens normalisés, mots vides retirés.

    Passe par `slugify` pour hériter de la même normalisation d'accents que les
    clés : une seule définition de « même chaîne » dans tout le module.
    """
    parts = [p for p in slugify(name).split("-") if p]
    kept = [p for p in parts if p not in _NAME_STOPWORDS]
    return frozenset(kept or parts)   # un nom entièrement vide de sens reste comparable


def similarity(a: str, b: str) -> float:
    """Proximité de deux noms, dans [0, 1] — déterministe, sans modèle.

    Jaccard sur les tokens, RELEVÉ par l'inclusion : « Severian » ⊂ « Severian
    le bourreau » donne 1/3 en Jaccard brut alors que le second est presque
    toujours une désignation du premier. On retient le max des deux mesures.
    """
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    inter = len(ta & tb)
    if not inter:
        return 0.0
    jaccard = inter / len(ta | tb)
    containment = inter / min(len(ta), len(tb))
    return max(jaccard, containment)


def split_aliases(raw: Any) -> list[str]:
    """Alias sous n'importe quelle forme (liste, csv `|`, vide) → liste propre."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple, set, frozenset)):
        items = [str(x) for x in raw]
    else:
        items = str(raw).split("|")
    seen: dict[str, str] = {}
    for item in items:
        item = item.strip()
        if item and slugify(item) not in seen:
            seen[slugify(item)] = item
    return list(seen.values())


def props_for(label: str) -> dict[str, str]:
    """Propriétés autorisées pour un label (communes + spécifiques)."""
    label = _label(label, WORLD_NODE_TABLES)
    return {**_COMMON_PROPS, **_TYPE_PROPS[label]}


def node_ddl(label: str) -> str:
    """DDL de la table de nœuds — dérivé de `props_for`, jamais écrit en dur."""
    cols = ", ".join(f"{k} {t}" for k, t in props_for(label).items())
    return f"CREATE NODE TABLE IF NOT EXISTS {label}({cols}, created TIMESTAMP, updated TIMESTAMP, PRIMARY KEY(id))"


def edge_ddl(edge: str) -> str:
    """DDL multi-couples d'une table d'arêtes (syntaxe Kuzu ≥ 0.7)."""
    edge = _label(edge, WORLD_EDGE_TABLES)
    pairs = ", ".join(f"FROM {a} TO {b}" for a, b in WORLD_EDGE_PAIRS[edge])
    return f"CREATE REL TABLE IF NOT EXISTS {edge}({pairs}, {_EDGE_PROPS})"


def edge_group_ddl(edge: str) -> str:
    """Repli pour Kuzu < 0.7, où le multi-couples s'appelle REL TABLE GROUP.

    Même surface de requête (`MATCH (a)-[r:KNOWS]->(b)`), autre mot-clé. On ne
    peut pas deviner la version installée sans ouvrir une base : on tente, et on
    retombe. Le mode retenu est exposé dans `rel_mode` — pas de magie muette.
    """
    edge = _label(edge, WORLD_EDGE_TABLES)
    pairs = ", ".join(f"FROM {a} TO {b}" for a, b in WORLD_EDGE_PAIRS[edge])
    return f"CREATE REL TABLE GROUP IF NOT EXISTS {edge}({pairs}, {_EDGE_PROPS})"


def _literal(value: Any, kuzu_type: str) -> str:
    """Sérialise une valeur Python en littéral Cypher selon le type déclaré.

    Le typage vient du schéma, pas de la valeur : un `danger="12"` renvoyé par
    un LLM doit atterrir en INT64, pas en chaîne.
    """
    if kuzu_type == "BOOL":
        if isinstance(value, str):
            return "true" if value.strip().lower() in ("1", "true", "vrai", "yes", "oui") else "false"
        return "true" if bool(value) else "false"
    if kuzu_type in ("INT64", "DOUBLE"):
        num = _num(value, 0)
        return str(int(num)) if kuzu_type == "INT64" else str(float(num))
    if isinstance(value, (list, tuple, set)):
        value = ",".join(str(v) for v in value)
    return f"'{_esc(value)}'"


# Kuzu pose un VERROU FICHIER par base : deux `kuzu.Database` sur le même
# chemin lèvent « Could not set lock on file ». Or plusieurs mondes partagent
# volontairement une seule base (le cloisonnement est dans la clé, pas dans le
# fichier) — la connexion doit donc être partagée par CHEMIN, pas par instance.
_CONNECTIONS: dict[str, tuple[Any, Any, str]] = {}


def _open(db_path: str) -> tuple[Any, Any, str]:
    """Ouvre (ou réutilise) la connexion Kuzu d'un chemin, schéma créé une fois."""
    cached = _CONNECTIONS.get(db_path)
    if cached is not None:
        return cached

    import kuzu  # import tardif : dépendance optionnelle
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)
    rel_mode = _create_schema(conn)
    _CONNECTIONS[db_path] = (db, conn, rel_mode)
    logger.info("[WorldKG] Kuzu initialisé — %s (rel_mode=%s)", db_path, rel_mode)
    return _CONNECTIONS[db_path]


def _create_schema(conn) -> str:
    """Crée les tables si absentes ; renvoie la syntaxe d'arête retenue."""
    for label in WORLD_NODE_TABLES:
        try:
            conn.execute(node_ddl(label))
        except Exception as e:          # table déjà là, ou moteur en désaccord
            logger.debug("[WorldKG] node table %s: %s", label, e)

    _migrate_schema(conn)

    rel_mode = "unknown"
    for edge in WORLD_EDGE_TABLES:
        try:
            conn.execute(edge_ddl(edge))
            rel_mode = "rel_table"
        except Exception as e_new:
            try:
                conn.execute(edge_group_ddl(edge))
                rel_mode = "rel_table_group"
            except Exception as e_old:
                rel_mode = "failed"
                logger.warning("[WorldKG] rel table %s non créée: %s / %s",
                               edge, e_new, e_old)
    return rel_mode


def table_columns(conn, label: str) -> set[str]:
    """Colonnes réellement présentes dans la table — vide si illisible."""
    try:
        res = conn.execute(f"CALL TABLE_INFO('{_esc(label)}') RETURN *")
    except Exception as e:
        logger.debug("[WorldKG] TABLE_INFO %s illisible: %s", label, e)
        return set()
    cols: set[str] = set()
    while res.has_next():
        row = res.get_next()
        # TABLE_INFO renvoie (property id, name, type, …) selon la version ;
        # on prend la première colonne textuelle qui ressemble à un nom.
        for cell in row:
            if isinstance(cell, str) and cell:
                cols.add(cell)
                break
    return cols


def _migrate_schema(conn) -> list[str]:
    """Ajoute les colonnes déclarées dans `_TYPE_PROPS` qui manquent en base.

    `CREATE NODE TABLE IF NOT EXISTS` ne touche PAS une table déjà créée : sans
    cette étape, ajouter une propriété au schéma n'aurait aucun effet sur une
    base existante et les écritures échoueraient sur une colonne inconnue —
    autrement dit la règle « pour étendre, ajouter dans `_TYPE_PROPS` » serait
    fausse dès la deuxième ouverture. Renvoie les colonnes ajoutées.
    """
    added: list[str] = []
    for label in WORLD_NODE_TABLES:
        present = table_columns(conn, label)
        if not present:            # table illisible : ne rien tenter à l'aveugle
            continue
        for prop, ktype in props_for(label).items():
            if prop in present:
                continue
            try:
                conn.execute(f"ALTER TABLE {_label(label, WORLD_NODE_TABLES)} "
                             f"ADD {prop} {ktype}")
                added.append(f"{label}.{prop}")
            except Exception as e:
                logger.warning("[WorldKG] colonne %s.%s non ajoutée: %s",
                               label, prop, e)
    if added:
        logger.info("[WorldKG] schéma réconcilié — colonnes ajoutées: %s",
                    ", ".join(added))
    return added


class WorldKG:
    """Graphe du monde (Kuzu embarqué), cloisonné par `world_id`.

    Lazy init comme `ForgeGraphDB` : la base n'est ouverte qu'au premier appel,
    pour qu'importer ce module reste gratuit quand Kuzu n'est pas installé.
    """

    def __init__(self, world_id: str = DEFAULT_WORLD_ID,
                 db_path: str | Path = WORLD_DB_PATH):
        self.world_id = slugify(world_id) or "default"
        self._db_path = str(db_path)
        self._conn = None
        self._initialized = False
        self.rel_mode = "unknown"   # "rel_table" | "rel_table_group" | "failed"

    # ── Cycle de vie ─────────────────────────────────────────────────────────

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        _db, self._conn, self.rel_mode = _open(self._db_path)
        self._initialized = True

    def close(self) -> None:
        """Détache CETTE instance. La base reste ouverte pour les autres mondes
        qui la partagent — seul `reset_world_kg()` la referme."""
        self._conn = None
        self._initialized = False

    # ── Écriture ─────────────────────────────────────────────────────────────

    def upsert(self, label: str, name: str, **props) -> str:
        """Crée ou met à jour un nœud du monde ; renvoie sa clé.

        Une propriété hors whitelist lève `ValueError` : un agent qui invente
        `character.hair_color` doit se voir refuser l'écriture plutôt que de
        croire l'avoir enregistrée. Le schéma se modifie dans `_TYPE_PROPS`.

        **E2-02 — unicité sémantique.** Avant toute création, le nom est résolu
        contre les entités existantes (clé exacte, puis alias déclarés, puis
        proximité). Une entité trop proche fait lever `DuplicateEntityError`.
        La contrainte est ICI, dans le chemin d'écriture, et non dans une
        fonction d'aide à côté : un garde qu'on peut contourner en appelant
        `upsert` directement ne garde rien.

        Deux sorties explicites, jamais implicites :
        - `allow_similar=True` — « je sais, ce sont bien deux entités » ;
        - `aliases=[...]` — « c'est la même, voici son autre nom » (met alors à
          jour l'entité existante au lieu d'en créer une seconde).
        """
        label = _label(label, WORLD_NODE_TABLES)
        allowed = props_for(label)
        allow_similar = bool(props.pop("allow_similar", False))
        if "aliases" in props:
            props["aliases"] = "|".join(split_aliases(props["aliases"]))
        node_id = world_key(self.world_id, label, name)

        canon = str(props.pop("canon", "generated"))
        if canon not in CANON_KINDS:
            raise ValueError(f"canon inconnu: {canon!r} — attendu {CANON_KINDS}")
        status = str(props.pop("status", "draft"))
        if status not in STATUS_KINDS:
            raise ValueError(f"status inconnu: {status!r} — attendu {STATUS_KINDS}")

        unknown = set(props) - set(allowed)
        if unknown:
            raise ValueError(
                f"propriétés inconnues pour {label}: {sorted(unknown)} — "
                f"autorisées: {sorted(allowed)}"
            )

        # Unicité sémantique APRÈS la validation des propriétés : celle-ci est
        # déterministe et sans I/O, celle-là interroge la base. Un appel fautif
        # sur les deux plans doit se voir reprocher sa faute la moins chère.
        if not self._exists(label, node_id):
            resolved = self.resolve(label, name)
            if resolved:                      # alias déclaré → c'est la MÊME entité
                node_id = resolved
                existing = self.get(label, node_id, by_id=True) or {}
                name = existing.get("name", name)
            elif not allow_similar:
                close = self.find_similar(label, name)
                if close:
                    top = close[0]
                    raise DuplicateEntityError(
                        f"{label} « {name} » ressemble à « {top['name']} » "
                        f"(score {top['score']:.2f}, seuil {SIMILARITY_THRESHOLD}). "
                        f"Si c'est la même entité, écrivez-la sous son nom existant "
                        f"ou ajoutez « {name} » à ses `aliases`. Si ce sont bien deux "
                        f"entités distinctes, passez `allow_similar=True`.",
                        candidates=close,
                    )

        if "aliases" in props:
            # Un alias déjà porté par une AUTRE entité rendrait le nom ambigu :
            # `resolve()` renverrait l'une ou l'autre selon l'ordre de parcours.
            # C'est le cœur de la contrainte — on refuse, on n'arbitre pas.
            for alias in split_aliases(props["aliases"]):
                owner = self.resolve(label, alias)
                if owner and owner != node_id:
                    raise DuplicateEntityError(
                        f"l'alias « {alias} » désigne déjà {label} "
                        f"« {(self.get(label, owner, by_id=True) or {}).get('name', owner)} ». "
                        f"Un nom ne peut pas désigner deux entités.",
                        candidates=[{"id": owner, "name": alias, "score": 1.0}],
                    )
            # Fusion, jamais remplacement : deux agents qui enrichissent la même
            # entité ne doivent pas s'effacer l'un l'autre.
            if self._exists(label, node_id):
                known = (self.get(label, node_id, by_id=True) or {}).get("aliases")
                props["aliases"] = "|".join(split_aliases(
                    "|".join(split_aliases(known) + split_aliases(props["aliases"]))
                ))

        values: dict[str, str] = {
            "id": _literal(node_id, "STRING"),
            "world_id": _literal(self.world_id, "STRING"),
            "name": _literal(name, "STRING"),
            "canon": _literal(canon, "STRING"),
            "status": _literal(status, "STRING"),
        }
        for key, val in props.items():
            if key in ("id", "world_id"):       # dérivées, non réassignables
                continue
            values[key] = _literal(val, allowed[key])

        self._ensure_init()
        exists = self._conn.execute(
            f"MATCH (n:{label}) WHERE n.id = '{_esc(node_id)}' RETURN n.id"
        ).has_next()

        if exists:
            sets = ", ".join(f"n.{k} = {v}" for k, v in values.items() if k != "id")
            self._conn.execute(
                f"MATCH (n:{label}) WHERE n.id = '{_esc(node_id)}' "
                f"SET {sets}, n.updated = current_timestamp()"
            )
        else:
            body = ", ".join(f"{k}: {v}" for k, v in values.items())
            self._conn.execute(
                f"CREATE (n:{label} {{{body}, "
                f"created: current_timestamp(), updated: current_timestamp()}})"
            )
        return node_id

    def link(self, edge: str, from_label: str, from_name: str,
             to_label: str, to_name: str, weight: float = 1.0,
             context: str = "", provenance: str = "") -> bool:
        """Relie deux entités du monde. Le couple (from, to) doit être déclaré."""
        edge = _label(edge, WORLD_EDGE_TABLES)
        from_label = _label(from_label, WORLD_NODE_TABLES)
        to_label = _label(to_label, WORLD_NODE_TABLES)
        if (from_label, to_label) not in WORLD_EDGE_PAIRS[edge]:
            raise ValueError(
                f"{edge} n'accepte pas {from_label}->{to_label} — "
                f"couples valides: {WORLD_EDGE_PAIRS[edge]}"
            )
        src = world_key(self.world_id, from_label, from_name)
        dst = world_key(self.world_id, to_label, to_name)

        self._ensure_init()
        try:
            self._conn.execute(
                f"MATCH (a:{from_label}), (b:{to_label}) "
                f"WHERE a.id = '{_esc(src)}' AND b.id = '{_esc(dst)}' "
                f"CREATE (a)-[r:{edge} {{weight: {_num(weight, 1.0)}, "
                f"context: '{_esc(context)}', provenance: '{_esc(provenance)}'}}]->(b)"
            )
            return True
        except Exception as e:
            logger.debug("[WorldKG] link %s %s->%s: %s", edge, src, dst, e)
            return False

    # Raccourcis typés — un seul appel `upsert`, aucune logique propre.
    def add_character(self, name: str, **p) -> str: return self.upsert("Character", name, **p)
    def add_faction(self, name: str, **p) -> str: return self.upsert("Faction", name, **p)
    def add_location(self, name: str, **p) -> str: return self.upsert("Location", name, **p)
    def add_quest(self, name: str, **p) -> str: return self.upsert("Quest", name, **p)
    def add_item(self, name: str, **p) -> str: return self.upsert("Item", name, **p)
    def add_ability(self, name: str, **p) -> str: return self.upsert("Ability", name, **p)
    def add_event(self, name: str, **p) -> str: return self.upsert("Event", name, **p)
    def add_lore_rule(self, name: str, **p) -> str: return self.upsert("LoreRule", name, **p)
    def add_dialogue(self, name: str, **p) -> str: return self.upsert("DialogueNode", name, **p)
    def add_decision(self, name: str, **p) -> str: return self.upsert("DesignDecision", name, **p)

    # ── Lecture ──────────────────────────────────────────────────────────────

    def _rows(self, query: str) -> list[dict]:
        """Exécute et renvoie des dicts aux clés NUES.

        Kuzu nomme les colonnes d'un `RETURN n.*` d'après l'alias : `n.hard`,
        pas `hard`. Laisser fuiter ce préfixe force chaque appelant à connaître
        l'alias de la requête — et fait échouer en silence tout filtre écrit
        `row.get("hard")` (bug réel : les règles de lore dures ne remontaient
        jamais dans `context_pack`). On dépréfixe ici, une fois pour toutes.
        """
        result = self._conn.execute(query)
        cols = [c.split(".", 1)[1] if "." in c else c for c in result.get_column_names()]
        out = []
        while result.has_next():
            out.append(dict(zip(cols, result.get_next())))
        return out

    def get(self, label: str, name: str, by_id: bool = False) -> Optional[dict]:
        """Entité par son nom, ou directement par sa clé si `by_id=True`.

        `by_id` évite un aller-retour quand on tient déjà la clé — et surtout
        évite de la recalculer depuis un nom résolu, ce qui la ferait diverger
        quand le nom d'appel était un alias.
        """
        label = _label(label, WORLD_NODE_TABLES)
        node_id = str(name) if by_id else world_key(self.world_id, label, name)
        self._ensure_init()
        rows = self._rows(f"MATCH (n:{label}) WHERE n.id = '{_esc(node_id)}' RETURN n.*")
        return rows[0] if rows else None

    # ── E2-02 · Résolution d'identité ────────────────────────────────────────

    def _exists(self, label: str, node_id: str) -> bool:
        self._ensure_init()
        return self._conn.execute(
            f"MATCH (n:{label}) WHERE n.id = '{_esc(node_id)}' RETURN n.id"
        ).has_next()

    def aliases_of(self, label: str, name: str) -> list[str]:
        """Alias déclarés d'une entité (liste vide si inconnue)."""
        node = self.get(label, name)
        return split_aliases(node.get("aliases")) if node else []

    def resolve(self, label: str, name: str) -> Optional[str]:
        """Nom → clé de l'entité qu'il désigne réellement, ou `None`.

        Ordre : clé exacte, puis alias déclaré. La proximité n'entre PAS ici —
        résoudre sur une ressemblance fusionnerait deux entités sans que
        personne l'ait décidé. La ressemblance alerte (`find_similar`), elle ne
        décide pas.
        """
        label = _label(label, WORLD_NODE_TABLES)
        node_id = world_key(self.world_id, label, name)
        if self._exists(label, node_id):
            return node_id
        target = slugify(name)
        for node in self.all_nodes(label, limit=2000):
            if any(slugify(a) == target for a in split_aliases(node.get("aliases"))):
                return node.get("id")
        return None

    def find_similar(self, label: str, name: str,
                     threshold: float | None = None,
                     limit: int = 5) -> list[dict]:
        """Entités existantes dont le nom (ou un alias) est proche de `name`.

        Balayage complet du label : à l'échelle d'un monde de jeu (milliers de
        nœuds, écritures rares) c'est négligeable, et ça évite un index à tenir
        cohérent. Si un monde atteint la centaine de milliers d'entités, c'est
        ici qu'il faudra un index inversé sur les tokens — pas avant.
        """
        label = _label(label, WORLD_NODE_TABLES)
        cutoff = SIMILARITY_THRESHOLD if threshold is None else float(threshold)
        self_key = world_key(self.world_id, label, name)
        out: list[dict] = []
        for node in self.all_nodes(label, limit=2000):
            if node.get("id") == self_key:
                continue
            names = [str(node.get("name", ""))] + split_aliases(node.get("aliases"))
            score = max((similarity(name, other) for other in names if other), default=0.0)
            if score >= cutoff:
                out.append({"id": node.get("id"), "name": node.get("name"),
                            "score": round(score, 4)})
        out.sort(key=lambda r: (-r["score"], str(r["name"])))
        return out[:limit]

    def all_nodes(self, label: str, limit: int = 200) -> list[dict]:
        label = _label(label, WORLD_NODE_TABLES)
        self._ensure_init()
        return self._rows(
            f"MATCH (n:{label}) WHERE n.world_id = '{_esc(self.world_id)}' "
            f"RETURN n.* LIMIT {int(_num(limit, 200))}"
        )

    def find(self, label: str, needle: str, limit: int = 50) -> list[dict]:
        """Recherche par sous-chaîne sur le nom (insensible à la casse)."""
        label = _label(label, WORLD_NODE_TABLES)
        self._ensure_init()
        return self._rows(
            f"MATCH (n:{label}) WHERE n.world_id = '{_esc(self.world_id)}' "
            f"AND lower(n.name) CONTAINS '{_esc(str(needle).lower())}' "
            f"RETURN n.* LIMIT {int(_num(limit, 50))}"
        )

    def neighbors(self, label: str, name: str, limit: int = 50) -> list[dict]:
        """Voisinage direct (les deux sens) d'une entité."""
        label = _label(label, WORLD_NODE_TABLES)
        node_id = world_key(self.world_id, label, name)
        self._ensure_init()
        lim = int(_num(limit, 50))
        out = self._rows(
            f"MATCH (a:{label})-[r]->(b) WHERE a.id = '{_esc(node_id)}' "
            f"RETURN label(r) AS edge, 'out' AS dir, b.id AS other_id, "
            f"b.name AS other_name, r.context AS context LIMIT {lim}"
        )
        out += self._rows(
            f"MATCH (a)-[r]->(b:{label}) WHERE b.id = '{_esc(node_id)}' "
            f"RETURN label(r) AS edge, 'in' AS dir, a.id AS other_id, "
            f"a.name AS other_name, r.context AS context LIMIT {lim}"
        )
        return out

    def all_edges(self, limit: int = 100000) -> list[dict]:
        """TOUTES les arêtes du monde — une requête par table, pas par nœud.

        `neighbors()` répond pour UNE entité ; l'appeler en boucle pour cartographier
        le monde coûte deux requêtes par nœud. Mesuré sur un monde de 300 nœuds :
        2 087 ms nœud-par-nœud contre 27 ms ici (×76), et ce coût-ci ne dépend que
        du nombre d'ARÊTES, pas du nombre de nœuds. C'est ce qui rend tenable la
        reconstruction complète de l'index de recherche à chaque requête (E2-05) —
        donc l'absence pure et simple de la panne « index périmé ».

        Même forme de ligne que `neighbors()` (`edge`/`other_id`/`other_name`/
        `context`), plus `src_id`/`src_name` : un appelant qui indexe doit savoir
        de quel côté il est. Les deux sens sont rendus par une seule arête stockée.
        """
        self._ensure_init()
        lim = int(_num(limit, 100000))
        out: list[dict] = []
        for edge in WORLD_EDGE_TABLES:
            try:
                out += self._rows(
                    f"MATCH (a)-[r:{edge}]->(b) "
                    f"WHERE a.world_id = '{_esc(self.world_id)}' "
                    f"RETURN '{edge}' AS edge, a.id AS src_id, a.name AS src_name, "
                    f"b.id AS other_id, b.name AS other_name, "
                    f"r.context AS context LIMIT {lim}"
                )
            except Exception as e:
                logger.debug("[WorldKG] all_edges %s: %s", edge, e)
        return out

    def context_pack(self, label: str, name: str, limit: int = 40) -> dict:
        """Le monde, tel qu'un agent doit le lire AVANT d'écrire.

        Renvoie l'entité + son voisinage + les règles de lore dures du monde.
        C'est le point d'entrée prévu pour E2-05 (re-ranking) et E7 (procgen) :
        aucun agent ne doit inventer un PNJ sans avoir consommé ce paquet.
        """
        entity = self.get(label, name)
        if entity is None:
            return {"found": False, "world_id": self.world_id,
                    "label": label, "name": name}
        return {
            "found": True,
            "world_id": self.world_id,
            "entity": entity,
            "neighbors": self.neighbors(label, name, limit=limit),
            "hard_rules": [r for r in self.all_nodes("LoreRule", limit=limit)
                           if r.get("hard")],
        }

    def contradictions(self, limit: int = 100) -> list[dict]:
        """Toutes les arêtes CONTRADICTS du monde — matière première d'E9."""
        self._ensure_init()
        return self._rows(
            f"MATCH (a)-[r:CONTRADICTS]->(b) "
            f"WHERE a.world_id = '{_esc(self.world_id)}' "
            f"RETURN a.id AS source, b.id AS target, r.context AS context, "
            f"r.weight AS severity LIMIT {int(_num(limit, 100))}"
        )

    def chronology(self, limit: int = 200) -> list[dict]:
        """Événements ordonnés par rang chronologique interne (E9)."""
        self._ensure_init()
        return self._rows(
            f"MATCH (e:Event) WHERE e.world_id = '{_esc(self.world_id)}' "
            f"RETURN e.id AS id, e.name AS name, e.era AS era, e.chrono AS chrono "
            f"ORDER BY e.chrono LIMIT {int(_num(limit, 200))}"
        )

    def count_nodes(self) -> dict:
        """Compte par label pour le monde courant."""
        self._ensure_init()
        counts = {}
        for label in WORLD_NODE_TABLES:
            try:
                rows = self._rows(
                    f"MATCH (n:{label}) WHERE n.world_id = '{_esc(self.world_id)}' "
                    f"RETURN count(n) AS c"
                )
                counts[label] = int(rows[0]["c"]) if rows else 0
            except Exception as e:
                logger.debug("[WorldKG] count %s: %s", label, e)
                counts[label] = 0
        return counts


_WORLDS: dict[str, WorldKG] = {}


def get_world_kg(world_id: str = DEFAULT_WORLD_ID) -> WorldKG:
    """Singleton par monde — une connexion Kuzu par `world_id`."""
    key = slugify(world_id) or "default"
    if key not in _WORLDS:
        _WORLDS[key] = WorldKG(world_id=key)
    return _WORLDS[key]


def reset_world_kg() -> None:
    """Détache tous les mondes ET referme les bases partagées."""
    for kg in _WORLDS.values():
        kg.close()
    _WORLDS.clear()
    _CONNECTIONS.clear()


if __name__ == "__main__":
    # Self-check : le schéma se rend sans Kuzu (DDL = fonction pure).
    print(f"WorldKG — {len(WORLD_NODE_TABLES)} types de nœuds, "
          f"{len(WORLD_EDGE_TABLES)} types d'arêtes")
    for _lbl in WORLD_NODE_TABLES:
        print(f"  {_lbl:<15} {len(props_for(_lbl))} propriétés")
    for _edg in WORLD_EDGE_TABLES:
        print(f"  {_edg:<15} {len(WORLD_EDGE_PAIRS[_edg])} couples autorisés")
    print(f"\nbase: {WORLD_DB_PATH}")
    try:
        import kuzu  # noqa: F401
        print("kuzu: disponible — self-check d'écriture possible")
    except ImportError:
        print("kuzu: ABSENT dans cet interpréteur — schéma non vérifié à l'exécution")
