"""
world_gdd.py — GDD vivant, généré depuis le graphe (ticket E2-04)
==================================================================
Le World-KG (E2-01) sait CE QU'EST le monde, le journal des décisions (E2-06)
sait POURQUOI. Ce module est l'endroit où les deux se lisent ensemble, sous la
forme que l'humain attend d'un projet de jeu : un Game Design Document.

**Le document est une VUE, jamais la source de vérité.** C'est la phrase du
ticket, et c'est une contrainte technique, pas une posture : un GDD édité à la
main diverge du monde dès la session suivante, et c'est toujours le document
qu'on croit. On régénère, on n'édite pas — et `write()` REFUSE d'écraser un
fichier qui a été retouché à la main (cf. `HandEditedGDDError`), parce que la
seule façon sûre de tuer un document généré est de détruire une fois le travail
de quelqu'un.

CE QU'IL N'EST PAS
------------------
**Ce n'est pas une troisième ontologie.** Aucun label, aucune propriété, aucune
arête ajoutée : `_SECTIONS` ne fait que donner un ORDRE de lecture aux 10 types
d'E2-01. Un GDD qui aurait eu besoin d'un type « Pitch » ou « Système » aurait
débordé de son ticket — ces nœuds n'existent pas, donc le document ne prétend
pas les rendre.

**Ce n'est pas un rapport de complétude.** Un GDD d'apparence complète sur un
monde à moitié vide est pire qu'un document manquant : il fait croire que le
travail est fait. `gaps()` remonte les trous DANS le document, et l'en-tête
compte ce qui a été écarté au lieu de le taire.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.world_gdd import get_gdd

    g = get_gdd("urth")
    print(g.render())              # le GDD en markdown
    g.write()                      # → 05_STATE (cloisonné tenant), refuse si édité
    g.gaps()                       # les trous, nommément

CINQ DÉCISIONS (toutes observées contre le moteur, aucune déduite)
-----------------------------------------------------------------
1. **`cut` disparaît du document, mais pas du décompte.** E2-01 déclarait déjà
   que `status` « pilote ce qui entre dans le GDD » ; c'est ici que ça devient
   vrai. Une entité écartée n'est PAS listée — sinon `cut` ne veut rien dire —
   mais l'en-tête dit combien l'ont été. Omettre en silence serait mentir par
   soustraction.
2. **Aucun horodatage dans le corps.** Sondé : `created`/`updated` reviennent en
   `datetime`. Les rendre ferait diverger deux générations d'un monde inchangé,
   et le diff — le seul moyen de voir ce qui a bougé dans le monde entre deux
   sessions — deviendrait du bruit. Le document est donc DÉTERMINISTE : même
   graphe, mêmes octets. Git sait déjà quand.
3. **Un `chrono` absent ne casse pas la chronologie.** Sondé : une propriété non
   fournie revient à `None`, pas `""` — et trier `[10, None]` lève un
   `TypeError` qui emporterait tout le document pour un seul événement mal
   saisi. Les événements sans rang sont donc rangés en fin de liste ET signalés
   comme trou : un trou visible, jamais une exception.
4. **La troncature est dite.** Sondé : `all_nodes(limit=2)` sur 3 entités en
   renvoie 2, sans un mot. Un GDD tronqué en silence est exactement le
   « document d'apparence complète » qu'on refuse ici : si un label rend
   autant de lignes que la limite, le document le déclare.
5. **C'est `validated` qu'on signale, pas `draft`.** Le premier jet marquait
   les brouillons ; mesuré sur un monde de sonde, le badge est tombé sur 11
   entités sur 13 — parce que `draft` est la valeur par défaut d'`upsert()`,
   que personne n'a choisie. Un marqueur universel n'informe pas : il apprend
   à être ignoré, donc à rater le vrai brouillon isolé dans un chapitre arrêté.
   On signale l'acte délibéré, et l'en-tête donne la part validée.

Vérification : `python -m forge_agents.world_gdd` · `pytest test_world_gdd.py`
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Optional

from .world_decisions import DECISION_LABEL, DecisionJournal, label_of, split_list
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path
from .world_kg import (
    DEFAULT_WORLD_ID,
    STATUS_KINDS,
    WORLD_NODE_TABLES,
    WorldKG,
    get_world_kg,
    props_for,
    slugify,
)

#: Statuts qui n'entrent PAS dans le document. C'est la seule raison d'être de
#: `cut` — E2-01 le déclarait, E2-04 l'applique.
HIDDEN_STATUS: tuple[str, ...] = ("cut",)

#: Statuts SIGNALÉS dans le document. `validated`, et non `draft` : mesuré sur
#: un monde de sonde, marquer `draft` posait un badge sur 11 entités sur 13,
#: parce que c'est la valeur PAR DÉFAUT d'`upsert()` — personne ne l'a choisie.
#: Un marqueur que tout le monde porte n'informe personne, et il apprend au
#: lecteur à l'ignorer, donc à rater le vrai brouillon isolé dans un chapitre
#: arrêté. On signale l'acte DÉLIBÉRÉ (« ceci est validé ») ; le brouillon est
#: l'état non marqué, et l'en-tête en donne la part.
MARKED_STATUS: tuple[str, ...] = ("validated",)

#: Ce qui tient lieu de « substance » selon le type. Sans cette table, `gaps()`
#: réclamait un `summary` à une décision de design entièrement documentée
#: (question/choix/rationale) et à une règle de lore dont l'énoncé était écrit :
#: des faux positifs, et une liste de trous à faux positifs est une liste qu'on
#: cesse de lire.
_SUBSTANCE: dict[str, str] = {
    DECISION_LABEL: "rationale",
    "LoreRule": "statement",
}

#: Le trou correspondant, dit en français plutôt qu'en nom de colonne.
_SUBSTANCE_GAP: dict[str, str] = {
    "summary": "sans résumé",
    "rationale": "sans justification",
    "statement": "sans énoncé",
}

#: Propriétés sérialisées en `a|b|c` (même séparateur que les alias, E2-02).
#: Les rendre brutes ferait apparaître le format de stockage dans un document
#: destiné à un humain.
_PIPE_PROPS = frozenset(("alternatives",))

#: Propriétés communes rendues à la main (en-tête d'entité). Tout le reste de
#: `props_for(label)` est du détail de type et se rend automatiquement — une
#: propriété ajoutée à `_TYPE_PROPS` apparaît donc dans le GDD sans toucher ici.
_HANDLED_PROPS = frozenset((
    "id", "world_id", "name", "summary", "tags", "aliases",
    "canon", "status", "provenance",
))

#: Marqueur d'intégrité en tête de fichier. Porte le sha256 du CORPS généré :
#: si le corps sur disque ne correspond plus, le fichier a été édité à la main.
_LOCK_RE = re.compile(r"^<!-- gdd-lock sha256:([0-9a-f]{64}) -->\s*$", re.M)


class Section(NamedTuple):
    """Un chapitre du document : un titre, et les labels qu'il rend."""
    key: str
    title: str
    labels: tuple[str, ...]


#: L'ORDRE de lecture du GDD. Ne déclare aucun type — il les range.
#: **Invariant verrouillé par un test : chaque label de `WORLD_NODE_TABLES`
#: apparaît dans exactement une section.** Sans ça, ajouter un 11ᵉ type à E2-01
#: le ferait disparaître du document en silence, et personne ne le verrait
#: puisqu'un document ne dit pas ce qu'il ne contient pas.
_SECTIONS: tuple[Section, ...] = (
    Section("regles",       "Règles du monde",      ("LoreRule",)),
    Section("factions",     "Factions",             ("Faction",)),
    Section("lieux",        "Lieux",                ("Location",)),
    Section("personnages",  "Personnages",          ("Character",)),
    Section("quetes",       "Quêtes",               ("Quest",)),
    Section("objets",       "Objets & capacités",   ("Item", "Ability")),
    Section("chronologie",  "Chronologie",          ("Event",)),
    Section("dialogues",    "Dialogues",            ("DialogueNode",)),
    Section("decisions",    "Décisions de design",  (DECISION_LABEL,)),
)


class HandEditedGDDError(RuntimeError):
    """Le fichier cible a été modifié à la main : régénérer l'écraserait.

    Porte `path`. La sortie est explicite (`force=True`) — jamais implicite :
    perdre une fois le travail d'un humain suffit à ce que plus personne ne
    régénère le document, et un GDD qu'on ne régénère plus est mort.
    """

    def __init__(self, message: str, path: Path):
        super().__init__(message)
        self.path = path


def _text(value: Any) -> str:
    """Valeur de propriété → texte affichable.

    Sondé : une propriété non fournie revient à `None`, pas à `""`. Tout le
    rendu passe par ici, sinon chaque site d'affichage doit y penser (et un
    seul oubli met « None » dans le document livré).
    """
    if value is None or value is False:
        return ""
    if value is True:
        return "oui"
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(v) for v in value if str(v).strip())
    return str(value).strip()


def visible(node: dict) -> bool:
    """L'entité entre-t-elle dans le document ?

    Un `status` vide ou inconnu est VISIBLE : n'afficher que les statuts connus
    ferait disparaître du document toute entité écrite avant que le vocabulaire
    ne soit fixé. On cache ce qui a été explicitement écarté, rien d'autre.
    """
    return _text(node.get("status")).lower() not in HIDDEN_STATUS


def _sort_key(node: dict) -> tuple:
    """Ordre stable : slug d'abord (accents neutralisés), nom en départage."""
    name = _text(node.get("name"))
    return (slugify(name), name)


def _chrono_key(node: dict) -> tuple:
    """Ordre chronologique, événements sans rang en fin.

    Le sentinelle en tête du tuple évite la comparaison `int` vs `None`, qui
    lève et emporterait le document entier pour un seul événement mal saisi.
    """
    chrono = node.get("chrono")
    if chrono is None:
        return (1, 0, *_sort_key(node))
    return (0, int(chrono), *_sort_key(node))


class LivingGDD:
    """Le GDD d'un monde : `build()` produit les données, `render()` la vue.

    La séparation n'est pas cosmétique — elle permet de vérifier le contenu
    (ce que le document dit du monde) sans dépendre de sa mise en forme, et de
    re-rendre un même `build()` sans réinterroger le graphe.
    """

    def __init__(self, kg: WorldKG, journal: Optional[DecisionJournal] = None):
        self.kg = kg
        # `DecisionJournal(kg)` et non `get_journal(world_id)` : le singleton
        # d'E2-06 s'adosse à `get_world_kg`, qui ouvre la base PAR DÉFAUT. Sur
        # un `kg` de test (base temporaire) les deux ne parleraient pas du même
        # monde, et le journal serait vide sans que rien ne le signale.
        self.journal = journal if journal is not None else DecisionJournal(kg)

    # ── Données ──────────────────────────────────────────────────────────────

    def _entity(self, label: str, node: dict) -> dict:
        """Une entité prête à rendre : en-tête, détails typés, liens, pourquoi.

        Le voisinage est lu UNE fois et sert aux deux usages (relations et
        « pourquoi »). Passer par `DecisionJournal.why()` aurait re-interrogé le
        graphe deux fois par entité pour la liste qu'on tient déjà ; on réutilise
        donc son vocabulaire exporté (`DECISION_LABEL`, `label_of`) plutôt que
        son implémentation. Un test verrouille l'accord des deux lectures.
        """
        name = _text(node.get("name"))
        details = {}
        for prop in sorted(set(props_for(label)) - _HANDLED_PROPS):
            text = (", ".join(split_list(node.get(prop))) if prop in _PIPE_PROPS
                    else _text(node.get(prop)))
            if text:
                details[prop] = text

        because: list[str] = []
        relations: list[dict] = []
        for nb in self.kg.neighbors(label, name, limit=2000):
            other_label = label_of(_text(nb.get("other_id")))
            is_decision = (nb.get("edge") == "DERIVED_FROM"
                           and nb.get("dir") == "out"
                           and other_label == DECISION_LABEL)
            if is_decision:
                because.append(_text(nb.get("other_name")))
                continue
            relations.append({
                "edge": _text(nb.get("edge")),
                "dir": _text(nb.get("dir")),
                "label": other_label,
                "name": _text(nb.get("other_name")),
                "context": _text(nb.get("context")),
            })
        relations.sort(key=lambda r: (r["dir"], r["edge"], slugify(r["name"])))

        return {
            "label": label,
            "name": name,
            "status": _text(node.get("status")),
            "canon": _text(node.get("canon")),
            "summary": _text(node.get("summary")),
            "tags": _text(node.get("tags")),
            "aliases": split_list(node.get("aliases")),
            "details": details,
            "relations": relations,
            "because": sorted(set(because)),
            "marked": _text(node.get("status")).lower() in MARKED_STATUS,
        }

    def build(self, limit: int = 500) -> dict:
        """Le monde tel que le document le dira — données seules, pas de mise en forme."""
        sections: list[dict] = []
        hidden = 0
        truncated: list[str] = []
        traced = 0
        total = 0

        for section in _SECTIONS:
            entities: list[dict] = []
            for label in section.labels:
                rows = self.kg.all_nodes(label, limit=limit)
                if len(rows) >= limit:
                    truncated.append(label)
                shown = [r for r in rows if visible(r)]
                hidden += len(rows) - len(shown)
                order = _chrono_key if label == "Event" else _sort_key
                for node in sorted(shown, key=order):
                    entities.append(self._entity(label, node))
            total += len(entities)
            traced += sum(1 for e in entities
                          if e["because"] and e["label"] != DECISION_LABEL)
            sections.append({"key": section.key, "title": section.title,
                             "labels": list(section.labels), "entities": entities})

        decidable = sum(len(s["entities"]) for s in sections
                        if DECISION_LABEL not in s["labels"])
        return {
            "world_id": self.kg.world_id,
            "sections": sections,
            "total": total,
            "hidden": hidden,
            "validated": sum(1 for s in sections for e in s["entities"] if e["marked"]),
            "decidable": decidable,
            "traced": traced,
            "truncated": sorted(set(truncated)),
            "gaps": self.gaps(limit=limit),
        }

    # ── Les trous ────────────────────────────────────────────────────────────

    def gaps(self, limit: int = 500) -> list[dict]:
        """Ce que le document ne peut pas dire, et pourquoi — nommément.

        Un GDD dont les trous sont invisibles fait croire le travail fait. Rien
        n'est deviné ici : chaque entrée pointe une entité et un manque réel.
        """
        out: list[dict] = []

        def add(kind: str, label: str, name: str, detail: str = "") -> None:
            out.append({"kind": kind, "label": label, "name": name, "detail": detail})

        names: dict[str, str] = {}          # clé → nom, pour rendre les contradictions
        for label in WORLD_NODE_TABLES:
            rows = self.kg.all_nodes(label, limit=limit)
            if len(rows) >= limit:
                add("troncature", label, "",
                    f"{len(rows)} entités rendues pour une limite de {limit} — "
                    f"le document est probablement incomplet")
            substance = _SUBSTANCE.get(label, "summary")
            for node in sorted((r for r in rows if visible(r)), key=_sort_key):
                name = _text(node.get("name"))
                names[_text(node.get("id"))] = f"{label} « {name} »"
                # Une règle DURE sans énoncé a son propre trou, plus grave : ne
                # pas la compter deux fois, un doublon dans une liste de trous
                # fait douter du décompte entier.
                hard_gap = (label == "LoreRule" and node.get("hard")
                            and not _text(node.get("statement")))
                if hard_gap:
                    add("règle dure sans énoncé", label, name,
                        "une règle inviolable qui ne dit pas ce qu'elle interdit "
                        "ne peut être ni appliquée ni contredite")
                elif not _text(node.get(substance)):
                    add(_SUBSTANCE_GAP[substance], label, name)
                if label == "Quest" and not _text(node.get("objective")):
                    add("quête sans objectif", label, name)
                if label == "Event" and node.get("chrono") is None:
                    add("événement hors chronologie", label, name,
                        "sans `chrono`, « avant/après » n'est qu'une phrase")

        for name in self.journal.orphans(limit=limit):
            add("décision sans conséquence", DECISION_LABEL, name,
                "non appliquée, ou `affects` non renseigné")

        # `contradictions()` ne rend que des clés (`monde:Label:slug`). Les
        # afficher telles quelles montrerait la plomberie interne à un game
        # designer ; l'index de noms construit ci-dessus les traduit.
        for row in self.kg.contradictions(limit=limit):
            source, target = _text(row.get("source")), _text(row.get("target"))
            add("contradiction", "", names.get(source, source),
                f"contredit {names.get(target, target)}"
                + (f" — {_text(row.get('context'))}" if _text(row.get("context")) else ""))

        # Tri sur le slug : trier les libellés bruts placerait « événement » APRÈS
        # « sans résumé » (le « é » d'un accent pèse plus qu'un « z » en ordre
        # de points de code). Déterministe dans les deux cas, lisible dans un seul.
        out.sort(key=lambda g: (slugify(g["kind"]), g["label"], slugify(g["name"])))
        return out

    # ── La vue ───────────────────────────────────────────────────────────────

    def render(self, data: Optional[dict] = None, limit: int = 500) -> str:
        """Le GDD en markdown. Déterministe : même graphe, mêmes octets.

        Aucun horodatage dans le corps — deux générations d'un monde inchangé
        doivent produire un diff VIDE, sans quoi on ne peut plus lire dans le
        diff ce qui a bougé dans le monde.
        """
        d = data if data is not None else self.build(limit=limit)
        lines: list[str] = [
            f"# GDD — monde « {d['world_id']} »",
            "",
            "> Document **généré** depuis le World-KG. La source de vérité est le "
            "graphe, jamais ce fichier : toute correction se fait sur les entités, "
            "puis on régénère.",
            "",
        ]

        pct = round(100 * d["traced"] / d["decidable"], 1) if d["decidable"] else 0.0
        lines.append(f"- {d['total']} entité(s) au document")
        if d["hidden"]:
            lines.append(f"- {d['hidden']} entité(s) écartée(s) (`cut`) — non listées ici")
        lines.append(f"- {d['validated']}/{d['total']} validée(s) — le reste est en "
                     f"brouillon (`draft` est la valeur par défaut : personne ne l'a choisi)")
        lines.append(f"- {d['traced']}/{d['decidable']} rattachée(s) à une décision "
                     f"de design ({pct} %)")
        if d["truncated"]:
            lines.append(f"- ⚠ **document tronqué** sur : {', '.join(d['truncated'])}")
        lines.append("")

        if not d["total"]:
            lines += ["_Le monde est vide : il n'y a rien à documenter._", "",
                      "Ce n'est pas un GDD en attente de mise en forme — c'est un "
                      "monde qui n'a pas encore été écrit.", ""]

        for section in d["sections"]:
            lines.append(f"## {section['title']}")
            lines.append("")
            if not section["entities"]:
                lines += ["_Aucune entité._", ""]
                continue
            if section["labels"] == [DECISION_LABEL]:
                lines.append("_Vue compacte. Le journal complet (alternatives écartées, "
                             "révisions, chaîne de remplacement) est rendu par "
                             "`DecisionJournal.render()` — E2-06._")
                lines.append("")
            for entity in section["entities"]:
                lines += (self._render_decision(entity)
                          if entity["label"] == DECISION_LABEL
                          else self._render_entity(entity))
            lines.append("")

        lines += self._render_gaps(d["gaps"])
        return "\n".join(lines).rstrip() + "\n"

    def _render_decision(self, e: dict) -> list[str]:
        """Une décision, en vue compacte : le choix et ce qu'il a produit.

        Recopier l'ADR entier ici ferait deux documents à tenir d'accord sur le
        même sujet — et E2-06 possède déjà cette vue. Le GDD CITE les décisions,
        il ne les re-rend pas.
        """
        d = e["details"]
        lines = [f"### {e['name']}" + ("  ⟨validée⟩" if e["marked"] else "")]
        if d.get("question"):
            lines.append(f"**Question** — {d['question']}")
        if d.get("choice"):
            lines.append(f"**Choix** — {d['choice']}")
        if d.get("rationale"):
            lines.append(f"**Pourquoi** — {d['rationale']}")
        # Les conséquences d'une décision arrivent en arêtes ENTRANTES : ce sont
        # les entités qui en découlent. Les rendre comme un voisinage brut
        # (« ← DERIVED_FROM ») dirait le schéma, pas le sens.
        produced = [f"{r['label']} « {r['name']} »" for r in e["relations"]
                    if r["edge"] == "DERIVED_FROM" and r["dir"] == "in"]
        lines.append("**Conséquences** — " + (", ".join(produced) if produced
                                              else "_aucune entité rattachée_"))
        lines.append("")
        return lines

    def _render_entity(self, e: dict) -> list[str]:
        flag = "  ⟨validée⟩" if e["marked"] else ""
        head = f"### {e['name']}{flag}"
        lines = [head]
        if e["aliases"]:
            lines.append(f"*aussi : {', '.join(e['aliases'])}*")
        if e["summary"]:
            lines.append(e["summary"])
        if e["details"]:
            lines.append("- " + " · ".join(f"**{k}** {v}" for k, v in e["details"].items()))
        if e["tags"]:
            lines.append(f"- *tags* : {e['tags']}")
        # `canon` n'est pas décoratif : il dit d'où vient l'affirmation. Le taire
        # présenterait du matériau de source comme une création propre — c'est
        # précisément ce que le gate copyright (E3-07) devra pouvoir trancher.
        if e["canon"] and e["canon"] != "generated":
            lines.append(f"- *provenance* : {e['canon']}")
        if e["relations"]:
            rendered = [
                f"{'→' if r['dir'] == 'out' else '←'} {r['edge']} "
                f"{r['label']} « {r['name']} »"
                + (f" ({r['context']})" if r["context"] else "")
                for r in e["relations"]
            ]
            lines.append("- " + " · ".join(rendered))
        if e["because"]:
            lines.append(f"- **Pourquoi** : {', '.join(e['because'])}")
        lines.append("")
        return lines

    def _render_gaps(self, gaps: Iterable[dict]) -> list[str]:
        gaps = list(gaps)
        lines = ["## Trous connus", ""]
        if not gaps:
            lines += ["_Aucun trou détecté._", ""]
            return lines
        lines.append(f"{len(gaps)} point(s) — le document ne les tait pas, "
                     f"il ne peut simplement pas les combler.")
        lines.append("")
        current = ""
        for gap in gaps:
            if gap["kind"] != current:
                current = gap["kind"]
                lines.append(f"**{current}**")
            target = f"{gap['label']} « {gap['name']} »" if gap["label"] else gap["name"]
            lines.append(f"- {target}" + (f" — {gap['detail']}" if gap["detail"] else ""))
        lines.append("")
        return lines

    # ── Écriture ─────────────────────────────────────────────────────────────

    def default_path(self) -> Path:
        """Où le GDD se pose par défaut — cloisonné par tenant.

        Un GDD est intégralement dérivé du monde d'un client : l'écrire dans le
        `05_STATE` GLOBAL le rendrait lisible d'un tenant à l'autre. `state_path`
        est le minimum (isolation seule, cf. son propre docstring) et c'est ce
        que le régime `tenant` exige de ce module.

        L'import de `state_path` est en tête de module et GARDÉ (`try/except
        ImportError`) : c'est la convention des modules migrés en W5-03a, et
        `test_state_isolation.py` la verrouille — un import relatif nu casse
        tout module qu'une porte de CI lance en script. Le premier jet l'avait
        rendu paresseux ici ; la suite complète l'a refusé, à raison.
        """
        return state_path(f"gdd_{self.kg.world_id}.md")

    def write(self, path: str | Path | None = None, force: bool = False,
              limit: int = 500) -> Path:
        """Écrit le GDD ; REFUSE d'écraser un fichier retouché à la main.

        Le fichier porte en tête un `gdd-lock` = sha256 de son propre corps. Si
        le corps sur disque ne correspond plus au verrou, quelqu'un a édité le
        document — régénérer détruirait son travail, et une seule perte de ce
        type suffit à ce que plus personne ne régénère (donc à tuer le GDD
        vivant). Un fichier sans verrou est traité de la même façon : on ne
        présume jamais qu'un fichier qu'on n'a pas écrit est jetable.
        """
        target = Path(path) if path else self.default_path()
        body = self.render(limit=limit)

        if target.exists():
            previous = target.read_text(encoding="utf-8-sig")
            edited, reason = _detect_hand_edit(previous)
            if edited and not force:
                raise HandEditedGDDError(
                    f"{target} {reason}. Le GDD est une VUE : reportez la "
                    f"correction sur les entités du monde puis régénérez, ou "
                    f"passez `force=True` pour assumer la perte.",
                    path=target,
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_with_lock(body), encoding="utf-8")
        return target


def _body_hash(body: str) -> str:
    """sha256 du corps, sur des fins de ligne normalisées.

    Git (`core.autocrlf`) et les éditeurs Windows réécrivent les `\\n` en
    `\\r\\n` sans rien changer au contenu : hacher les octets bruts ferait
    crier « édité à la main » au premier aller-retour par le dépôt.
    """
    return hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _with_lock(body: str) -> str:
    """Corps + marqueur d'intégrité en tête."""
    return f"<!-- gdd-lock sha256:{_body_hash(body)} -->\n{body}"


def _detect_hand_edit(content: str) -> tuple[bool, str]:
    """Le fichier a-t-il été modifié depuis sa génération ? (booléen, raison)."""
    match = _LOCK_RE.search(content)
    if not match:
        return True, "ne porte pas de marqueur `gdd-lock` (fichier non généré par ce module)"
    body = content[match.end():].lstrip("\n")
    if _body_hash(body) != match.group(1):
        return True, "a été modifié à la main depuis sa génération"
    return False, ""


_GDDS: dict[str, LivingGDD] = {}


def get_gdd(world_id: str = DEFAULT_WORLD_ID) -> LivingGDD:
    """GDD du monde demandé — adossé au singleton `get_world_kg`."""
    kg = get_world_kg(world_id)
    if kg.world_id not in _GDDS or _GDDS[kg.world_id].kg is not kg:
        _GDDS[kg.world_id] = LivingGDD(kg)
    return _GDDS[kg.world_id]


def reset_gdds() -> None:
    """Détache les GDD. `reset_world_kg()` reste à appeler séparément."""
    _GDDS.clear()


if __name__ == "__main__":  # self-check — n'ouvre aucune base
    covered = [lbl for s in _SECTIONS for lbl in s.labels]
    missing = [lbl for lbl in WORLD_NODE_TABLES if lbl not in covered]
    print(f"GDD vivant — {len(_SECTIONS)} sections, {len(covered)} labels rangés")
    for _s in _SECTIONS:
        print(f"  {_s.key:<13} {_s.title:<22} {', '.join(_s.labels)}")
    print(f"labels non rangés (doit être vide) : {missing or 'aucun'}")
    print(f"statuts cachés : {HIDDEN_STATUS} · signalés : {MARKED_STATUS} "
          f"· vocabulaire E2-01 : {STATUS_KINDS}")
    print("substance par type :", ", ".join(f"{k}→{v}" for k, v in _SUBSTANCE.items()),
          "(défaut : summary)")
    _demo = "# GDD\n\ncorps\n"
    print("verrou d'exemple :", _with_lock(_demo).splitlines()[0])
    print("édité à la main ?", _detect_hand_edit(_with_lock(_demo))[0],
          "| après retouche :", _detect_hand_edit(_with_lock(_demo) + "ajout")[0])
