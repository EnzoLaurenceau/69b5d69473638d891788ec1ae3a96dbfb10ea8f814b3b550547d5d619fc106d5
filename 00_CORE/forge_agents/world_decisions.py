"""
world_decisions.py — Journal des décisions de design (ticket E2-06)
===================================================================
Le World-KG (E2-01) sait CE QU'EST le monde. Il ne savait pas POURQUOI il est
ainsi. Ce module est ce chaînon : chaque choix de design devient un nœud
`DesignDecision`, et chaque entité qui en découle porte une arête `DERIVED_FROM`
vers lui. « Pourquoi ce PNJ est-il mortel ? » cesse d'être une question qu'on
pose à l'auteur pour devenir une requête sur le graphe.

C'est le ticket qui sert l'objectif S2 de l'audit — *reprendre un projet entre
deux sessions sans perte*. Une décision non écrite est une décision qu'on
re-litigera à la session suivante, avec un résultat différent.

CE QU'IL N'EST PAS
------------------
**Ce n'est pas une seconde ontologie.** La table `DesignDecision` et l'arête
`DERIVED_FROM` existent depuis E2-01 ; ce module ne crée aucun label, n'ajoute
aucune propriété, ne touche pas à `_TYPE_PROPS`. Il ne fait que câbler ce qui
était déjà déclaré — et refuser d'écrire un journal qui mentirait.

**Ce n'est pas un garde du chemin d'écriture** (contrairement à E2-02, qui
devait vivre DANS `upsert()` sous peine d'être contourné). Ici il n'y a aucun
invariant à protéger : `kg.add_decision()` en direct reste parfaitement légitime
— il enregistre une décision qui n'affecte encore rien. Un module à côté est
donc le bon niveau, et il garde `world_kg.py` sur son seul sujet : l'ontologie
et l'identité.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.world_decisions import get_journal

    j = get_journal("urth")
    j.decide("perma-mort", question="Le joueur peut-il mourir définitivement ?",
             choice="Oui, hors sanctuaire", rationale="La tension retombe si...",
             alternatives=["mort douce", "checkpoints"], decided_by="game-design",
             affects=[("Character", "Severian"), ("Quest", "La Griffe")])

    j.why("Character", "Severian")     # → les décisions dont ce PNJ découle
    j.affected_by("perma-mort")        # → ce que cette décision a produit
    print(j.render())                  # → le journal en ADR markdown

TROIS DÉCISIONS (observées contre le vrai moteur, pas déduites)
---------------------------------------------------------------
1. **`affects` est vérifié AVANT d'écrire quoi que ce soit, et tout ou rien.**
   `WorldKG.link()` renvoie `True` quand la cible n'existe pas — le `MATCH` ne
   trouve rien, le `CREATE` ne fait rien, et Kùzu ne lève pas. Un journal bâti
   naïvement dessus enregistrerait une décision en revendiquant une traçabilité
   qu'il n'a pas : le pire résultat possible pour un outil dont l'unique raison
   d'être est la traçabilité. On résout donc chaque cible d'abord, et on lève
   `UntraceableDecisionError` si l'une manque — avant la moindre écriture.
2. **Les arêtes sont posées une seule fois.** `link()` appelé deux fois crée
   deux arêtes identiques (vérifié) : `why()` listerait alors deux fois la même
   décision. Re-déclarer une décision inchangée doit être sans effet.
3. **« Remplacée par » se LIT dans le graphe, il ne se stocke pas.** Ajouter un
   `"superseded"` à `STATUS_KINDS` aurait modifié une constante d'E2-01 partagée
   par les 10 types (un `Character` « superseded » ne veut rien dire). La
   révision est donc une arête `DERIVED_FROM` portant `context="supersedes"` :
   zéro octet touché dans l'ontologie, et la chaîne des révisions devient une
   requête au lieu d'un champ à tenir cohérent.

Vérification : `python -m forge_agents.world_decisions` · `pytest test_world_decisions.py`
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from .world_kg import (
    DEFAULT_WORLD_ID,
    WorldKG,
    get_world_kg,
    slugify,
    split_aliases,
    world_key,
)

#: Le label porté par une décision. Déclaré en E2-01, pas ici.
DECISION_LABEL = "DesignDecision"

#: Marqueur porté par le `context` de l'arête quand une décision en REMPLACE une
#: autre. Discrimine la révision (« ceci annule cela ») de la simple filiation
#: (« ceci s'appuie sur cela ») — les deux sont des `DERIVED_FROM`.
SUPERSEDES = "supersedes"


class UntraceableDecisionError(ValueError):
    """`affects` désigne une entité que le monde ne connaît pas.

    Levée AVANT toute écriture : mieux vaut pas de décision qu'une décision
    dont la traçabilité est un mensonge silencieux.
    """

    def __init__(self, message: str, missing: Sequence[tuple[str, str]] = ()):
        super().__init__(message)
        self.missing = list(missing)


def _join(value: Any) -> str:
    """Liste → chaîne `a|b|c`, sur le même séparateur que les alias.

    Une alternative de design peut contenir une virgule (« mort douce, sans
    perte d'objets ») ; `tags` est en csv, pas ce champ.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, frozenset)):
        return "|".join(str(v).strip() for v in value if str(v).strip())
    return str(value)


def split_list(raw: Any) -> list[str]:
    """`a|b|c` → `["a", "b", "c"]`. Inverse de `_join`, tolérant au vide."""
    return split_aliases(raw)


def label_of(node_id: str) -> str:
    """Label encodé dans une clé `{world}:{Label}:{slug}` (cf. `world_key`).

    Évite une requête pour savoir de quel type est un voisin : `neighbors()`
    renvoie déjà la clé, et la clé porte le label. Une requête de moins par
    voisin, sur un appel qui en parcourt des dizaines.
    """
    parts = str(node_id).split(":")
    return parts[1] if len(parts) >= 3 else ""


class DecisionJournal:
    """Le « pourquoi » du monde, adossé au World-KG.

    Ne détient aucun état propre : la vérité reste dans le graphe, ce qui évite
    le écueil classique du journal de décisions — un document qui diverge du
    monde qu'il prétend expliquer.
    """

    def __init__(self, kg: WorldKG):
        self.kg = kg

    # ── Écriture ─────────────────────────────────────────────────────────────

    def _resolve(self, label: str, name: str) -> Optional[tuple[str, str]]:
        """(clé, nom canonique) de l'entité désignée, ou `None` si inconnue.

        Passe par `resolve()` d'E2-02 : `affects=[("Character", "le bourreau")]`
        atteint donc Severian si l'alias est déclaré. On renvoie le nom canonique
        parce que `link()` re-calcule la clé depuis le nom — la lui donner sous
        son alias produirait une arête vers une entité qui n'existe pas.
        """
        node_id = self.kg.resolve(label, name)
        if not node_id:
            return None
        node = self.kg.get(label, node_id, by_id=True) or {}
        return node_id, str(node.get("name") or name)

    def _link_once(self, edge: str, from_label: str, from_name: str,
                   to_label: str, to_name: str, context: str = "",
                   provenance: str = "") -> bool:
        """Pose l'arête si elle n'y est pas déjà. Renvoie True si créée.

        `link()` ne déduplique pas : deux appels identiques produisent deux
        arêtes, et `why()` afficherait deux fois la même décision. Re-déclarer
        une décision inchangée doit être un no-op, pas une accumulation.
        """
        target = world_key(self.kg.world_id, to_label, to_name)
        for nb in self.kg.neighbors(from_label, from_name, limit=2000):
            if (nb.get("edge") == edge and nb.get("dir") == "out"
                    and nb.get("other_id") == target
                    and str(nb.get("context") or "") == context):
                return False
        return self.kg.link(edge, from_label, from_name, to_label, to_name,
                            context=context, provenance=provenance)

    def decide(self, name: str, question: str = "", choice: str = "",
               rationale: str = "", alternatives: Any = (),
               decided_by: str = "", affects: Iterable[tuple[str, str]] = (),
               supersedes: str = "", status: str = "",
               summary: str = "", tags: Any = "",
               allow_similar: bool = False) -> dict:
        """Enregistre une décision de design et la relie à ce qu'elle produit.

        `name` est le titre court de l'ADR (« perma-mort ») : c'est lui qui fait
        la clé, donc re-`decide()` sous le même nom MET À JOUR la décision. Pour
        acter un changement d'avis, on crée une NOUVELLE décision avec
        `supersedes="<ancien nom>"` — un journal qui s'écrase n'est pas un
        journal. Un champ non fourni n'efface JAMAIS ce qui est déjà écrit :
        préciser le seul `choice` ne fait pas disparaître le rationale.

        `affects` accepte les alias (E2-02) et lève `UntraceableDecisionError`
        si une cible est inconnue, **avant** d'écrire la décision.

        Note E2-02 : « perma-mort » et « perma-mort v2 » se ressemblent assez
        pour que l'unicité sémantique refuse la seconde. C'est le comportement
        voulu — une révision est un acte délibéré : `allow_similar=True`.
        """
        targets: list[tuple[str, str, str]] = []
        missing: list[tuple[str, str]] = []
        for label, entity in affects:
            found = self._resolve(label, entity)
            if found is None:
                missing.append((label, entity))
            else:
                targets.append((label, found[1], entity))
        if missing:
            raise UntraceableDecisionError(
                f"décision « {name} » : {len(missing)} entité(s) inconnue(s) du "
                f"monde « {self.kg.world_id} » — "
                + ", ".join(f"{lbl} « {ent} »" for lbl, ent in missing)
                + ". Créez-les d'abord, ou retirez-les de `affects` : une "
                  "décision qui prétend tracer ce qui n'existe pas ne trace rien.",
                missing=missing,
            )

        prior: Optional[str] = None
        if supersedes:
            prior_found = self._resolve(DECISION_LABEL, supersedes)
            if prior_found is None:
                raise UntraceableDecisionError(
                    f"décision « {name} » : elle prétend remplacer "
                    f"« {supersedes} », qui n'existe pas.",
                    missing=[(DECISION_LABEL, supersedes)],
                )
            prior = prior_found[1]

        # Fusion, jamais remplacement — même doctrine que les alias d'E2-02. Une
        # re-déclaration partielle (« je précise juste le `choice` ») effacerait
        # sinon le rationale, les alternatives et l'auteur : pour un journal
        # dont le produit EST le « pourquoi », c'est la pire perte possible.
        # Vérifié : le premier jet écrasait bien ces champs.
        stored = self.get(name) or {}

        def kept(value: Any, field: str) -> str:
            text = str(value or "")
            return text if text else str(stored.get(field) or "")

        self.kg.upsert(
            DECISION_LABEL, name,
            question=kept(question, "question"), choice=kept(choice, "choice"),
            rationale=kept(rationale, "rationale"),
            alternatives=kept(_join(alternatives), "alternatives"),
            decided_by=kept(decided_by, "decided_by"),
            summary=kept(summary, "summary"), tags=kept(_join(tags), "tags"),
            provenance=kept(decided_by, "provenance"),
            status=kept(status, "status") or "draft", canon="human",
            allow_similar=allow_similar,
        )

        linked = 0
        for label, canonical, _asked in targets:
            if self._link_once("DERIVED_FROM", label, canonical,
                               DECISION_LABEL, name, provenance=str(decided_by)):
                linked += 1
        if prior:
            self._link_once("DERIVED_FROM", DECISION_LABEL, name,
                            DECISION_LABEL, prior, context=SUPERSEDES,
                            provenance=str(decided_by))

        return {
            "name": name,
            "id": world_key(self.kg.world_id, DECISION_LABEL, name),
            "affects": [(lbl, canonical) for lbl, canonical, _ in targets],
            "linked": linked,
            "supersedes": prior or "",
        }

    # ── Lecture ──────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[dict]:
        """La décision, par son nom ou l'un de ses alias."""
        node_id = self.kg.resolve(DECISION_LABEL, name)
        return self.kg.get(DECISION_LABEL, node_id, by_id=True) if node_id else None

    def why(self, label: str, name: str) -> list[dict]:
        """Les décisions dont cette entité découle — « pourquoi elle est ainsi ».

        Ne suit qu'un cran : les décisions directes. Remonter la filiation
        entière (décision → décision remplacée → …) se fait avec
        `supersede_chain()`, qui est une autre question.
        """
        out: list[dict] = []
        for nb in self.kg.neighbors(label, name, limit=2000):
            if (nb.get("edge") != "DERIVED_FROM" or nb.get("dir") != "out"
                    or label_of(nb.get("other_id", "")) != DECISION_LABEL):
                continue
            node = self.kg.get(DECISION_LABEL, nb["other_id"], by_id=True)
            if node:
                out.append(node)
        out.sort(key=lambda d: str(d.get("name", "")))
        return out

    def affected_by(self, name: str) -> list[dict]:
        """Ce que cette décision a produit : entités qui en découlent.

        Exclut les décisions qui la REMPLACENT — elles pointent vers elle par la
        même arête, mais ce ne sont pas des conséquences de design.
        """
        node = self.get(name)
        if node is None:
            return []
        out: list[dict] = []
        for nb in self.kg.neighbors(DECISION_LABEL, node["name"], limit=2000):
            if nb.get("edge") != "DERIVED_FROM" or nb.get("dir") != "in":
                continue
            if str(nb.get("context") or "") == SUPERSEDES:
                continue
            out.append({"label": label_of(nb.get("other_id", "")),
                        "id": nb.get("other_id"),
                        "name": nb.get("other_name")})
        out.sort(key=lambda r: (str(r["label"]), str(r["name"])))
        return out

    def superseded_by(self, name: str) -> list[str]:
        """Noms des décisions qui remplacent celle-ci (vide si elle est à jour)."""
        node = self.get(name)
        if node is None:
            return []
        return sorted(
            str(nb.get("other_name"))
            for nb in self.kg.neighbors(DECISION_LABEL, node["name"], limit=2000)
            if nb.get("edge") == "DERIVED_FROM" and nb.get("dir") == "in"
            and str(nb.get("context") or "") == SUPERSEDES
        )

    def supersede_chain(self, name: str) -> list[str]:
        """La décision, puis celle qu'elle remplace, etc. — du récent à l'ancien.

        Coupe sur un nom déjà vu : un cycle (A remplace B qui remplace A) est
        une donnée absurde mais possible, et une boucle infinie serait une
        façon particulièrement mauvaise de le signaler.
        """
        chain: list[str] = []
        seen: set[str] = set()
        current = self.get(name)
        while current is not None:
            key = slugify(str(current.get("name", "")))
            if key in seen:
                break
            seen.add(key)
            chain.append(str(current.get("name")))
            nxt = None
            for nb in self.kg.neighbors(DECISION_LABEL, current["name"], limit=2000):
                if (nb.get("edge") == "DERIVED_FROM" and nb.get("dir") == "out"
                        and str(nb.get("context") or "") == SUPERSEDES):
                    nxt = self.kg.get(DECISION_LABEL, nb["other_id"], by_id=True)
                    break
            current = nxt
        return chain

    def journal(self, limit: int = 200, include_superseded: bool = True) -> list[dict]:
        """Le journal complet : décisions + ce qu'elles ont produit + révisions."""
        rows: list[dict] = []
        for node in self.kg.all_nodes(DECISION_LABEL, limit=limit):
            name = str(node.get("name", ""))
            replaced_by = self.superseded_by(name)
            if replaced_by and not include_superseded:
                continue
            rows.append({
                **node,
                "alternatives_list": split_list(node.get("alternatives")),
                "affects": self.affected_by(name),
                "superseded_by": replaced_by,
                "current": not replaced_by,
            })
        rows.sort(key=lambda r: (str(r.get("created") or ""), str(r.get("name"))))
        return rows

    def orphans(self, limit: int = 200) -> list[str]:
        """Décisions qui n'ont rien produit — le trou visible du journal.

        Une décision sans conséquence est soit une décision non appliquée, soit
        un `affects` qu'on a oublié de renseigner. Les deux méritent d'être vues
        plutôt que de se dissoudre dans un journal d'apparence complète.
        """
        return sorted(str(r["name"]) for r in self.journal(limit=limit)
                      if not r["affects"] and not r["superseded_by"])

    def render(self, limit: int = 200) -> str:
        """Le journal en markdown ADR.

        **Le document est une VUE, jamais la source de vérité** — même doctrine
        que le GDD vivant (E2-04). On le régénère, on ne l'édite pas : un ADR
        modifié à la main diverge du graphe dès la première session suivante.
        """
        rows = self.journal(limit=limit)
        lines = [f"# Journal des décisions — monde « {self.kg.world_id} »", "",
                 f"{len(rows)} décision(s) · "
                 f"{sum(1 for r in rows if r['current'])} en vigueur", ""]
        if not rows:
            lines.append("_Aucune décision enregistrée._")
            return "\n".join(lines)

        for i, row in enumerate(rows, 1):
            flag = "" if row["current"] else "  ⟨remplacée⟩"
            lines.append(f"## {i}. {row.get('name')}{flag}")
            if row.get("question"):
                lines.append(f"**Question** — {row['question']}")
            if row.get("choice"):
                lines.append(f"**Choix** — {row['choice']}")
            if row.get("rationale"):
                lines.append(f"**Pourquoi** — {row['rationale']}")
            if row["alternatives_list"]:
                lines.append("**Écartées** — "
                             + ", ".join(row["alternatives_list"]))
            if row.get("decided_by"):
                lines.append(f"**Par** — {row['decided_by']}")
            if row["superseded_by"]:
                lines.append("**Remplacée par** — "
                             + ", ".join(row["superseded_by"]))
            if row["affects"]:
                lines.append("**Conséquences** — " + ", ".join(
                    f"{a['label']} « {a['name']} »" for a in row["affects"]))
            else:
                lines.append("**Conséquences** — _aucune entité rattachée_")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


_JOURNALS: dict[str, DecisionJournal] = {}


def get_journal(world_id: str = DEFAULT_WORLD_ID) -> DecisionJournal:
    """Journal du monde demandé — adossé au singleton `get_world_kg`."""
    kg = get_world_kg(world_id)
    if kg.world_id not in _JOURNALS or _JOURNALS[kg.world_id].kg is not kg:
        _JOURNALS[kg.world_id] = DecisionJournal(kg)
    return _JOURNALS[kg.world_id]


def reset_journals() -> None:
    """Détache les journaux. `reset_world_kg()` reste à appeler séparément."""
    _JOURNALS.clear()


if __name__ == "__main__":  # self-check — n'ouvre aucune base
    print(f"DecisionJournal — label {DECISION_LABEL}, marqueur « {SUPERSEDES} »")
    print("clé d'exemple :", world_key("urth", DECISION_LABEL, "perma-mort"))
    print("label déduit  :", label_of(world_key("urth", DECISION_LABEL, "perma-mort")))
    print("API :", ", ".join(m for m in dir(DecisionJournal)
                             if not m.startswith("_")))
