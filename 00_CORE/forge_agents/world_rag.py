"""
world_rag.py — Interroger le monde AVANT d'écrire (ticket E2-05)
=================================================================
E2-01 a donné `context_pack(label, name)` : le voisinage d'une entité, prêt à
entrer dans un prompt. Il lui manquait l'essentiel — **il faut déjà connaître le
nom de l'entité pour l'appeler**. Or un agent sur le point d'écrire « un marchand
de reliques dans la ville basse » ne connaît aucun nom : c'est précisément ce
qu'il s'apprête à inventer. Le paquet existait, la porte d'entrée manquait.

Ce module est cette porte : **du langage naturel vers le monde**. Recherche sur
l'ensemble des entités, re-classement, puis le `context_pack` des gagnantes.
C'est ce que « tout agent interroge le monde avant d'écrire » veut dire
concrètement, et `before_write()` en est la forme la plus courte.

CE QU'IL N'EST PAS
------------------
**Ce n'est pas une troisième ontologie** (même discipline qu'E2-04/E2-06) : aucun
label, aucune propriété, aucune arête. Un seul ajout à E2-01, `all_edges()`, et
c'est une LECTURE — mesurée, justifiée plus bas.

**Ce n'est pas un juge de cohérence.** `before_write()` REMONTE les règles dures
et les quasi-doublons ; il ne décide pas si l'écriture les viole. Trancher
« ce PNJ contredit-il la règle ? » demande un LLM, c'est E9 (LORE-GUARD). Un
module qui prétendrait le faire ici rendrait un verdict qu'il ne peut pas tenir —
et un garde-fou auquel on ne peut pas se fier est pire que pas de garde-fou.
La seule prédiction rendue (`would_raise`) est vérifiable : elle rejoue la règle
d'E2-02, et un test l'oppose au vrai `upsert()`.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.world_rag import get_world_rag

    r = get_world_rag("urth")
    r.search("bourreau de la guilde")          # → entités classées
    r.world_context("relique qui guérit")      # → LE paquet à injecter
    r.before_write("Character", "Severian le bourreau",
                   summary="marchand de reliques")   # → avant d'écrire

SEPT DÉCISIONS (toutes mesurées contre le vrai moteur, aucune déduite)
----------------------------------------------------------------------
1. **`forge_rag_optimized` NE S'IMPORTE PAS dans l'interpréteur de la Forge.**
   Mesuré : `import forge_rag_optimized` → `ModuleNotFoundError: torch`. Le
   module fait `import torch` au niveau module, donc même son BM25 (dont la
   dépendance, elle, est installée) est hors d'atteinte. Le brancher en dur
   aurait livré un E2-05 qui lève à l'import — un monde interrogeable nulle part.
   Il est donc chargé PARESSEUSEMENT et sert à ce qu'il est seul à savoir faire :
   le **cross-encoder de re-classement** (`rerank()`, l'étape que le ticket
   nomme). Le reste dégrade en trois étages annoncés (`mode`), jamais en silence :
   `rag_optimized` → `bm25` (rank_bm25, installé) → `lexical` (pur Python).
   Une recherche qui s'éteint sans le dire est un monde que les agents
   ré-inventeront à côté.
2. **Une entité = UN document, jamais découpé.** Mesuré : `semantic_chunk()`
   coupe une fiche d'entité de 805 caractères en 2 morceaux, et **le second ne
   contient plus le nom**. Un tel fragment (« il porte la Griffe et marche vers
   le nord ») remonterait attribué à personne. On n'appelle donc pas
   `ForgeRAGOptimized.index()` — qui découpe, et qui ré-encode en outre TOUT le
   corpus à chaque document ajouté (O(N²), lu dans son `index()`). Le corpus est
   tenu ici ; c'est son *reranker* qu'on branche, pas son indexeur.
3. **Le tokenizer partagé mutile le français, on le corrige par `slugify`.**
   Mesuré : `_tokenize("épée dorée")` → `['pée', 'dorée']` — la lettre accentuée
   INITIALE est mangée (son motif commence par `[a-zA-Z_]`). « épée » et « epee »
   ne se rencontrent alors jamais, dans un monde qui s'écrit en français. On
   tokenise donc le SLUG : `_tokens("épée dorée")` → `['epee', 'doree']`. Bonus
   qui n'en est pas un : la recherche hérite exactement de la notion de « même
   chaîne » que l'identité (E2-01/E2-02). Une seule définition dans le module.
4. **L'index est reconstruit à CHAQUE requête — il n'y a pas d'index périmé.**
   Un index qui se rafraîchit sur signal a toujours un chemin par lequel il ment,
   et un agent qui lit un monde périmé écrit contre un monde qui n'existe plus.
   Rendu tenable par `all_edges()` (E2-01, ajouté ici) : mesuré sur 300 nœuds,
   cartographier le voisinage nœud-par-nœud coûte 2 087 ms, en masse 27 ms
   (×76) — et ce coût ne dépend que du nombre d'ARÊTES. Relevé sur un monde de
   302 nœuds / 100 arêtes : reconstruction complète **91 ms**, donc **74 ms par
   requête** en mode par défaut contre 10 ms sur index tenu. C'est le bon
   arbitrage devant un agent qui s'apprête à écrire — l'appel LLM qui suit coûte
   des secondes. `fresh=False` reste la sortie explicite pour qui boucle sur un
   monde figé, et le seul réglage à connaître si un monde grossit beaucoup.
5. **Les règles DURES ne sont jamais classées.** Elles sont hissées hors du
   classement, entières, à côté des résultats. Un re-classement top-5 peut
   écarter la règle qui interdit exactement ce que l'agent s'apprête à écrire —
   et l'écarter d'autant plus sûrement qu'elle est formulée en termes généraux,
   donc lexicalement loin de la requête. Corollaire : elles sont retirées des
   `context_pack` individuels (E2-01 les y remet à chaque appel), sinon les mêmes
   règles sont payées k fois dans le prompt.
6. **Score nul = aucun résultat.** Mesuré : BM25 rend un vecteur entièrement nul
   sur une requête hors vocabulaire — et `np.argsort` d'un vecteur nul rend
   l'ordre des indices. `ForgeRAGOptimized.search_bm25()` renvoie donc ses
   `top_k` premiers documents, à score 0, comme s'ils répondaient. Ici, sous
   `MIN_SCORE`, on rend une liste vide : « le monde ne sait rien là-dessus » est
   une réponse, cinq entités au hasard n'en sont pas.
7. **Une entité NOMMÉE par la requête est hissée, pas classée.** Le premier jet
   la classait comme les autres, et échouait sur le cas le plus élémentaire :
   chercher « Severian » rendait Agia, la Griffe et l'Épée — **pas Severian**.
   Cause mesurée, structurelle et non un réglage à corriger : le nom d'une
   entité figure dans le document de CHACUN de ses voisins (on y rend les
   relations, et c'est voulu — « une rivale de Severian » doit trouver Agia).
   Le terme apparaît donc dans la majorité des documents, son IDF s'effondre au
   plancher d'epsilon de `rank_bm25`, et la normalisation par longueur classe
   l'entité elle-même DERNIÈRE (0,0059 contre 0,0078 pour ses voisins, relevé).
   Aucune pondération ne répare ça : un nom exact n'est pas un signal parmi
   d'autres, c'est une réponse. Il est donc traité comme les règles dures
   (décision 5) — hors classement. La correspondance de nom réutilise
   `similarity()` d'E2-02, et se mesure sur tout le corpus : c'est précisément
   quand la recherche rate l'entité qu'elle doit la rattraper.

Vérification : `python -m forge_agents.world_rag` · `pytest test_world_rag.py`
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Iterable, NamedTuple, Optional

from .semantic_cache import _tokenize
from .world_kg import (
    CANON_KINDS,
    DEFAULT_WORLD_ID,
    WORLD_NODE_TABLES,
    WorldKG,
    get_world_kg,
    name_tokens,
    props_for,
    similarity,
    slugify,
    split_aliases,
)

logger = logging.getLogger("WorldRAG")

#: Statuts qui n'entrent PAS dans le corpus. Même doctrine (et même valeur) que
#: `world_gdd.HIDDEN_STATUS` : une entité écartée du jeu ne doit pas être
#: proposée à un agent comme matière à réutiliser. On ne l'IMPORTE pas de là —
#: la recherche n'a pas à dépendre du module qui rend un document — mais un test
#: verrouille l'accord des deux valeurs, pour qu'une divergence se voie.
HIDDEN_STATUS: tuple[str, ...] = ("cut",)

#: Poids de provenance. `canon` pèse plus que `generated` parce qu'une
#: affirmation de source arbitre une contradiction que du contenu produit par un
#: agent ne peut pas arbitrer (cf. E2-01, vocabulaire `canon`).
CANON_WEIGHT: dict[str, float] = {
    "canon": 1.0, "human": 0.85, "derived": 0.6, "generated": 0.4,
}

#: Les cinq signaux du re-classement, et leur part. Somme = 1.0 (verrouillé par
#: un test : une part ajoutée sans rééquilibrage rendrait les scores
#: incomparables d'une version à l'autre).
RERANK_WEIGHTS: dict[str, float] = {
    "relevance": 0.55,   # cross-encoder si disponible, sinon score de recherche
    "name": 0.20,        # le nom (ou un alias) est-il DANS la requête
    "degree": 0.10,      # entité câblée dans le monde vs orpheline
    "canon": 0.10,       # d'où vient l'affirmation
    "status": 0.05,      # `validated` est un acte délibéré (cf. E2-04)
}

#: Plancher sous lequel un résultat n'en est pas un (cf. décision 6).
MIN_SCORE = float(os.getenv("FORGE_WORLD_RAG_MIN_SCORE", "0.02"))

#: Combien de candidats la recherche remonte au re-classement, et combien il en
#: garde. Même entonnoir que `forge_rag_optimized` (Top-20 → Top-5) : un
#: cross-encoder coûte trop cher pour tourner sur le corpus entier.
CANDIDATES = 20
TOP_K = 5

#: Le cross-encoder tronque à 256 tokens (lu dans `_CrossEncoder.predict`). Les
#: relations sont donc rendues EN DERNIER et plafonnées : ce qui identifie
#: l'entité (type, nom, alias, résumé) doit survivre à la troncature.
MAX_RELATIONS = 12


class WorldDoc(NamedTuple):
    """Une entité du monde, telle que la recherche la voit."""
    key: str
    label: str
    name: str
    aliases: tuple[str, ...]
    text: str
    tokens: tuple[str, ...]
    canon: str
    status: str
    degree: int
    hard: bool


def _tokens(text: str) -> list[str]:
    """Texte → tokens de recherche, accents neutralisés (cf. décision 3).

    `slugify` d'abord (sinon la première lettre accentuée est perdue), puis le
    tokenizer partagé, puis on jette les séparateurs : `slugify` produit des
    `-` que `_tokenize` rend comme des tokens à part entière et qui, présents
    dans TOUS les documents, ne discriminent rien.
    """
    return [t for t in _tokenize(slugify(text)) if t.isalnum()]


def _text(value: Any) -> str:
    """Valeur de propriété → texte. `None` (propriété non fournie) → chaîne vide."""
    if value is None or value is False:
        return ""
    if value is True:
        return "oui"
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(v) for v in value if str(v).strip())
    return str(value).strip()


#: Propriétés communes rendues à la main dans l'en-tête du document. Tout le
#: reste de `props_for(label)` est du détail de type et se rend automatiquement :
#: une propriété ajoutée à `_TYPE_PROPS` (E2-01) devient cherchable sans toucher
#: ici. Même mécanique que `world_gdd._HANDLED_PROPS`, pour la même raison.
_HANDLED = frozenset((
    "id", "world_id", "name", "summary", "tags", "aliases", "canon",
    "status", "provenance", "created", "updated",
))


def entity_text(label: str, node: dict, relations: Iterable[dict] = ()) -> str:
    """Une entité → le document que la recherche indexe.

    Déterministe (mêmes données, mêmes octets) et sans ligne vide : `semantic_chunk`
    coupe sur les lignes vides, et un document coupé perd son nom (décision 2).
    L'identité vient en tête, les relations en queue et plafonnées, parce que
    c'est la queue que le cross-encoder tronque.
    """
    lines = [f"{label} « {_text(node.get('name'))} »"]
    aliases = split_aliases(node.get("aliases"))
    if aliases:
        lines.append("aussi : " + ", ".join(aliases))
    if _text(node.get("summary")):
        lines.append(_text(node["summary"]))
    details = []
    for prop in sorted(set(props_for(label)) - _HANDLED):
        val = _text(node.get(prop))
        if val:
            details.append(f"{prop} {val}")
    if details:
        lines.append(" · ".join(details))
    if _text(node.get("tags")):
        lines.append("tags : " + _text(node["tags"]).replace(",", ", "))
    rendered = []
    for rel in list(relations)[:MAX_RELATIONS]:
        arrow = "→" if rel.get("dir") == "out" else "←"
        piece = f"{arrow} {_text(rel.get('edge'))} {_text(rel.get('other_name'))}"
        if _text(rel.get("context")):
            piece += f" ({_text(rel['context'])})"
        rendered.append(piece)
    if rendered:
        lines.append(" · ".join(rendered))
    return "\n".join(lines)


def _normalize(values: list[float]) -> list[float]:
    """Min-max, comme `ForgeRAGOptimized._normalize`.

    Un écart nul rend des zéros — et non des uns : quand tous les candidats se
    valent, le signal ne doit rien dire, pas tout affirmer.
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-10:
        return [0.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


class _Chunk:
    """Le strict nécessaire pour parler à un reranker (`text` + `rerank_score`).

    Volontairement pas `RAGChunk` : ce module ne peut pas l'importer là où
    `torch` manque (décision 1), et un reranker n'a jamais besoin du reste.
    """

    __slots__ = ("text", "rerank_score", "doc_id", "chunk_idx", "source", "metadata")

    def __init__(self, text: str, doc_id: str):
        self.text = text
        self.rerank_score = 0.0
        self.doc_id = doc_id
        self.chunk_idx = 0
        self.source = doc_id
        self.metadata: dict = {}


def load_reranker() -> tuple[Any, str]:
    """Charge le cross-encoder de `forge_rag_optimized`, ou dit pourquoi il manque.

    Renvoie `(moteur, mode)` — `(None, "graphe")` si l'import échoue. L'échec est
    NORMAL dans cette Forge (torch absent) et ne doit jamais remonter en
    exception : la recherche fonctionne sans lui, moins finement.
    """
    try:
        from .forge_rag_optimized import get_rag_optimized
    except Exception as e:                     # ModuleNotFoundError: torch, mesuré
        logger.info("[WorldRAG] cross-encoder indisponible (%s) — "
                    "re-classement par signaux de graphe", type(e).__name__)
        return None, "graphe"
    try:
        return get_rag_optimized(), "cross-encoder"
    except Exception as e:
        logger.warning("[WorldRAG] forge_rag_optimized importé mais inutilisable: %s", e)
        return None, "graphe"


class WorldRAG:
    """La recherche du monde : corpus, classement, paquet de contexte."""

    def __init__(self, kg: WorldKG, engine: Any = None, reranker_mode: str = ""):
        self.kg = kg
        # Injection : `engine` permet de vérifier la branche cross-encoder là où
        # `forge_rag_optimized` ne s'importe pas — c'est-à-dire ici. Sans elle,
        # cette branche ne serait couverte par aucun test de cette Forge.
        self._engine = engine
        self._reranker_mode = reranker_mode or ("cross-encoder" if engine else "")
        self._docs: Optional[list[WorldDoc]] = None
        self._bm25 = None
        self.mode = "lexical"
        self.excluded = 0

    # ── Corpus ───────────────────────────────────────────────────────────────

    def build(self, limit: int = 5000) -> list[WorldDoc]:
        """Le monde entier, projeté en documents cherchables.

        Une requête d'arêtes par TABLE (`all_edges`), pas deux par nœud : c'est
        ce qui rend la reconstruction systématique tenable (décision 4).
        """
        edges: dict[str, list[dict]] = {}
        for row in self.kg.all_edges():
            src, dst = _text(row.get("src_id")), _text(row.get("other_id"))
            edges.setdefault(src, []).append({
                "edge": row.get("edge"), "dir": "out",
                "other_id": dst, "other_name": row.get("other_name"),
                "context": row.get("context"),
            })
            edges.setdefault(dst, []).append({
                "edge": row.get("edge"), "dir": "in",
                "other_id": src, "other_name": row.get("src_name"),
                "context": row.get("context"),
            })

        docs: list[WorldDoc] = []
        excluded = 0
        for label in WORLD_NODE_TABLES:
            for node in self.kg.all_nodes(label, limit=limit):
                if _text(node.get("status")).lower() in HIDDEN_STATUS:
                    excluded += 1
                    continue
                key = _text(node.get("id"))
                rel = edges.get(key, [])
                text = entity_text(label, node, rel)
                aliases = tuple(split_aliases(node.get("aliases")))
                docs.append(WorldDoc(
                    key=key, label=label, name=_text(node.get("name")),
                    aliases=aliases, text=text, tokens=tuple(_tokens(text)),
                    canon=_text(node.get("canon")), status=_text(node.get("status")),
                    degree=len(rel), hard=bool(node.get("hard")),
                ))
        # Ordre stable : deux mondes identiques doivent produire le même index,
        # donc les mêmes départages à score égal.
        docs.sort(key=lambda d: (d.label, slugify(d.name), d.key))
        self.excluded = excluded
        return docs

    def refresh(self, limit: int = 5000) -> int:
        """Reconstruit corpus + index lexical. Renvoie le nombre de documents."""
        self._docs = self.build(limit=limit)
        self._bm25 = None
        self.mode = "lexical"
        if not self._docs:
            return 0
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi([list(d.tokens) or ["_"] for d in self._docs])
            self.mode = "rag_optimized" if self.reranker_mode == "cross-encoder" else "bm25"
        except Exception as e:
            logger.info("[WorldRAG] rank_bm25 indisponible (%s) — mode lexical",
                        type(e).__name__)
        return len(self._docs)

    @property
    def docs(self) -> list[WorldDoc]:
        if self._docs is None:
            self.refresh()
        return self._docs or []

    @property
    def reranker_mode(self) -> str:
        """« cross-encoder » ou « graphe » — chargé au premier besoin."""
        if not self._reranker_mode:
            self._engine, self._reranker_mode = load_reranker()
        return self._reranker_mode

    # ── Recherche ────────────────────────────────────────────────────────────

    def _retrieve(self, tokens: list[str]) -> list[float]:
        """Score de recherche brut, par document. BM25 si possible, sinon
        recouvrement de la requête — jamais rien."""
        docs = self.docs
        if self._bm25 is not None:
            return [float(s) for s in self._bm25.get_scores(tokens)]
        wanted = set(tokens)
        return [len(wanted & set(d.tokens)) / len(wanted) for d in docs]

    def _name_hit(self, query: str, doc: WorldDoc) -> float:
        """Le nom (ou un alias) est-il ce que la requête désigne ?

        Réutilise `similarity()` d'E2-02 : « quel nom désigne quelle entité » a
        déjà une définition dans ce monde, en avoir deux serait en avoir zéro.
        On mesure aussi le nom contre la requête ENTIÈRE, parce qu'un nom cité
        au milieu d'une phrase (« un rival de Severian ») est un signal fort que
        la comparaison nom-à-nom rate.
        """
        qt = name_tokens(query)
        best = 0.0
        for candidate in (doc.name, *doc.aliases):
            if not candidate:
                continue
            best = max(best, similarity(query, candidate))
            ct = name_tokens(candidate)
            if ct and ct <= qt:            # le nom entier apparaît dans la requête
                best = max(best, 1.0)
        return best

    def rerank(self, query: str, results: list[dict], top_k: int = TOP_K) -> list[dict]:
        """Re-classe les candidats — cross-encoder ET signaux de graphe.

        Le cross-encoder ne REMPLACE pas les signaux de graphe, il remplace la
        part « pertinence » du score. Un cross-encoder ignore tout du monde :
        il ne sait pas qu'une entité est câblée à trente autres, ni qu'elle vient
        du canon. Deux classements séparés selon la présence de `torch`
        auraient divergé sans que personne ne le voie ; il n'y a donc qu'un
        classement, dont un seul terme change de source.

        Les entités NOMMÉES par la requête sont hissées en tête sans passer par
        le score (cf. décision 7) ; le classement ordonne tout le reste.
        """
        if not results:
            return []

        relevance = _normalize([r["retrieval"] for r in results])
        if self.reranker_mode == "cross-encoder" and self._engine is not None:
            try:
                chunks = [_Chunk(r["text"], r["key"]) for r in results]
                ranked = self._engine.rerank(query, chunks, top_k=len(chunks))
                by_key = {c.doc_id: float(c.rerank_score) for c in ranked}
                relevance = _normalize([by_key.get(r["key"], 0.0) for r in results])
            except Exception as e:
                logger.warning("[WorldRAG] cross-encoder en échec (%s) — "
                               "repli sur le score de recherche", type(e).__name__)

        degrees = _normalize([math.log1p(r["degree"]) for r in results])
        w = RERANK_WEIGHTS
        for i, r in enumerate(results):
            signals = {
                "relevance": round(relevance[i], 4),
                "name": round(r["name_score"], 4),
                "degree": round(degrees[i], 4),
                "canon": CANON_WEIGHT.get(r["canon"], CANON_WEIGHT["generated"]),
                "status": 1.0 if r["status"].lower() == "validated" else 0.0,
            }
            r["signals"] = signals
            r["score"] = round(sum(w[k] * v for k, v in signals.items()), 4)
        # Nommées d'abord, puis le score. Départage par slug du nom : à score
        # égal, l'ordre ne doit pas dépendre de l'ordre de parcours de la base.
        results.sort(key=lambda r: (not r["named"], -r["score"],
                                    slugify(r["name"]), r["key"]))
        # Le plancher ne s'applique pas à une entité nommée : quand la requête
        # dit son nom, elle est une réponse quel que soit son score.
        return [r for r in results[:top_k] if r["named"] or r["score"] >= MIN_SCORE]

    def search(self, query: str, top_k: int = TOP_K, candidates: int = CANDIDATES,
               fresh: bool = True) -> list[dict]:
        """Langage naturel → entités du monde, classées.

        `fresh=True` par défaut : voir décision 4 (il n'y a pas d'index périmé).

        Les scores sont COMPARATIFS À L'INTÉRIEUR d'une requête, pas d'une
        requête à l'autre : la part « pertinence » est min-maxée sur les seuls
        candidats du moment. Un unique candidat parfait score donc bas. C'est
        assumé — un score absolu supposerait une échelle de pertinence que ni
        BM25 ni un cross-encoder ne fournissent.
        """
        if fresh or self._docs is None:
            self.refresh()
        docs = self.docs
        tokens = _tokens(query)
        if not docs or not tokens:
            return []

        # Le nom est mesuré sur TOUT le corpus, pas sur les seuls candidats de la
        # recherche : c'est justement quand la recherche rate l'entité qu'il doit
        # la rattraper (décision 7).
        names = [self._name_hit(query, d) for d in docs]
        scores = self._retrieve(tokens)
        order = sorted(range(len(docs)),
                       key=lambda i: (-(names[i] >= 1.0), -scores[i], docs[i].key))
        results: list[dict] = []
        for i in order[:max(int(candidates), int(top_k))]:
            # décision 6 : score nul ≠ résultat — sauf si la requête la NOMME.
            if scores[i] <= 0.0 and names[i] < 1.0:
                continue
            d = docs[i]
            results.append({
                "key": d.key, "label": d.label, "name": d.name, "text": d.text,
                "canon": d.canon, "status": d.status, "degree": d.degree,
                "retrieval": scores[i], "name_score": names[i],
                "named": names[i] >= 1.0, "doc": d,
            })
        return self.rerank(query, results, top_k=top_k)

    # ── Le paquet ────────────────────────────────────────────────────────────

    def hard_rules(self) -> list[dict]:
        """Les règles inviolables du monde — entières, hors de tout classement.

        Un `LoreRule` `hard` écarté par un top-5 est exactement la règle que
        l'agent va enfreindre (décision 5). Elles ne sont donc pas cherchées :
        elles sont jointes.
        """
        return [{"name": d.name, "statement": d.text.split("\n", 1)[-1],
                 "canon": d.canon, "key": d.key}
                for d in self.docs
                if d.label == "LoreRule" and d.hard]

    def world_context(self, query: str, top_k: int = TOP_K,
                      fresh: bool = True) -> dict:
        """LE paquet qu'un agent consomme avant d'écrire.

        Chaque entité retenue vient avec son `context_pack` d'E2-01 — une seule
        définition du « voisinage d'une entité » dans la Forge — mais AMPUTÉ de
        ses `hard_rules` : E2-01 les rejoint à chaque appel, les garder ferait
        payer les mêmes règles k fois dans le prompt. Elles sont hissées une
        seule fois au niveau du paquet.
        """
        hits = self.search(query, top_k=top_k, fresh=fresh)
        entities = []
        for hit in hits:
            pack = self.kg.context_pack(hit["label"], hit["name"])
            pack.pop("hard_rules", None)
            entities.append({
                "label": hit["label"], "name": hit["name"], "score": hit["score"],
                "signals": hit["signals"], "canon": hit["canon"],
                "status": hit["status"], "text": hit["text"], "pack": pack,
            })
        return {
            "found": bool(entities),
            "world_id": self.kg.world_id,
            "query": query,
            "mode": self.mode,
            "reranker": self.reranker_mode,
            "entities": entities,
            "hard_rules": self.hard_rules(),
            "considered": len(self.docs),
            "excluded": self.excluded,
        }

    def before_write(self, label: str, name: str, summary: str = "",
                     top_k: int = TOP_K, allow_similar: bool = False) -> dict:
        """Ce que le monde a à dire sur une écriture qui n'a pas encore eu lieu.

        Trois questions, trois réponses factuelles : que sait déjà le monde
        là-dessus (`entities`), qu'est-ce qui ressemble à ce que j'écris
        (`duplicates`, E2-02), qu'est-ce qui m'est interdit (`rules_in_scope`).

        `would_raise` rejoue la règle d'E2-02 pour dire si `upsert()` LÈVERAIT —
        c'est la seule prédiction du module, et elle est vérifiable : un test
        l'oppose au vrai `upsert()` dans les deux sens. Aucun jugement de
        cohérence n'est rendu ici : c'est E9.
        """
        pack = self.world_context(f"{name} {summary}".strip(), top_k=top_k)
        existing = self.kg.get(label, name)
        resolved = self.kg.resolve(label, name)
        duplicates = [] if existing else self.kg.find_similar(label, name)

        would_raise = ""
        if not existing and not resolved and duplicates and not allow_similar:
            top = duplicates[0]
            would_raise = (
                f"DuplicateEntityError — « {name} » ressemble à « {top['name']} » "
                f"(score {top['score']}). Écrire sous le nom existant, ajouter "
                f"« {name} » à ses `aliases`, ou passer `allow_similar=True`."
            )

        scope_of = lambda rule: _text(  # noqa: E731 — table de correspondance locale
            (self.kg.get("LoreRule", rule["name"]) or {}).get("scope"))
        pack.update({
            "target": {"label": label, "name": name},
            "existing": existing,
            "resolved_to": resolved if resolved and not existing else "",
            "duplicates": duplicates,
            "rules_in_scope": [r for r in pack["hard_rules"]
                               if scope_of(r) in ("", label)],
            "would_raise": would_raise,
        })
        return pack

    # ── Diagnostic ───────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Ce que la recherche sait, et par quel moteur elle répond."""
        docs = self.docs
        by_label: dict[str, int] = {}
        for d in docs:
            by_label[d.label] = by_label.get(d.label, 0) + 1
        return {
            "world_id": self.kg.world_id,
            "documents": len(docs),
            "by_label": by_label,
            "excluded_cut": self.excluded,
            "hard_rules": sum(1 for d in docs if d.label == "LoreRule" and d.hard),
            "edges_indexed": sum(d.degree for d in docs),
            "mode": self.mode,
            "reranker": self.reranker_mode,
        }


_RAGS: dict[str, WorldRAG] = {}


def get_world_rag(world_id: str = DEFAULT_WORLD_ID) -> WorldRAG:
    """Recherche du monde demandé — adossée au singleton `get_world_kg`."""
    kg = get_world_kg(world_id)
    if kg.world_id not in _RAGS or _RAGS[kg.world_id].kg is not kg:
        _RAGS[kg.world_id] = WorldRAG(kg)
    return _RAGS[kg.world_id]


def reset_world_rags() -> None:
    """Détache les moteurs. `reset_world_kg()` reste à appeler séparément."""
    _RAGS.clear()


if __name__ == "__main__":  # self-check — n'ouvre aucune base
    print(f"WorldRAG — 3 modes de recherche, {len(RERANK_WEIGHTS)} signaux de re-classement")
    print(f"  poids : {RERANK_WEIGHTS} (somme {sum(RERANK_WEIGHTS.values()):.2f})")
    print(f"  canon : {CANON_WEIGHT} · vocabulaire E2-01 : {CANON_KINDS}")
    print(f"  écartés du corpus : {HIDDEN_STATUS} · plancher : {MIN_SCORE}")
    _mangled = _tokenize("épée dorée")
    print(f"\ntokenizer partagé sur « épée dorée » : {_mangled}  ← lettre initiale mangée")
    print(f"corrigé par slugify                 : {_tokens('épée dorée')}")
    _node = {"name": "Sévérian", "summary": "Bourreau devenu Autarque.",
             "aliases": "le bourreau", "role": "protagoniste", "alive": True,
             "tags": "heros,guilde", "status": "validated", "canon": "canon"}
    _rel = [{"edge": "LOCATED_IN", "dir": "out", "other_name": "Nessus", "context": "exil"}]
    print("\ndocument d'entité :")
    for _line in entity_text("Character", _node, _rel).splitlines():
        print("   " + _line)
    _engine, _mode = load_reranker()
    print(f"\nre-classement disponible : {_mode}")
