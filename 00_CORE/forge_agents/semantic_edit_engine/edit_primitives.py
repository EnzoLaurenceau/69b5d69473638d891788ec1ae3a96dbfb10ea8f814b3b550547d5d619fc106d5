"""edit_primitives.py — primitives d'édition minimales (MCPT niveau 1/2).

4 primitives seulement (ponytail/YAGNI — les 9 autres de la liste initiale sont
des REFACTOS, pas des éditions, et relèvent d'un autre problème) :

    Replace(anchor, replacement)   — remplace la 1re occurrence d'une ancre textuelle
    InsertAfter(anchor, text)      — insère juste après une ancre, sans rien détruire
    DeleteRange(start, end)        — supprime un intervalle de caractères
    ReplaceSymbolBody(name, code)  — remplace le corps d'un symbole résolu (AST/regex)

Chaque primitive est :
  - APPLICABLE   : produit un nouveau contenu depuis l'ancien
  - MESURABLE    : `cost()` = nb de caractères que le LLM doit émettre pour l'exprimer
  - SÉRIALISABLE : `to_dict()` — un agent renvoie des OPS, pas du code réécrit

Self-check : python -m forge_agents.semantic_edit_engine.edit_primitives
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Optional


class EditError(ValueError):
    """Primitive inapplicable sur le contenu fourni (ancre absente, borne invalide)."""


# ═══════════════════════════════════════════════════════════════════════════════
# PRIMITIVES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EditOp:
    """Base — une opération d'édition atomique."""

    kind: str = "noop"

    def apply(self, content: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def cost(self) -> int:
        """Caractères que le LLM doit produire pour exprimer l'op (proxy tokens)."""
        return 0

    def to_dict(self) -> dict:
        return {"kind": self.kind}


@dataclass
class Replace(EditOp):
    """Remplace la première occurrence de `anchor` par `replacement`."""

    anchor: str = ""
    replacement: str = ""
    kind: str = field(default="Replace", init=False)

    def apply(self, content: str) -> str:
        if not self.anchor or self.anchor not in content:
            raise EditError(f"ancre introuvable: {self.anchor!r}")
        return content.replace(self.anchor, self.replacement, 1)

    def cost(self) -> int:
        return len(self.anchor) + len(self.replacement)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "anchor": self.anchor, "replacement": self.replacement}


@dataclass
class InsertAfter(EditOp):
    """Insère `text` juste après la première occurrence de `anchor`.

    C'est LA primitive du cas d'école `if(user){` → `if(user && user.isActive){` :
    on n'efface rien, on ajoute ` && user.isActive` après l'ancre `user`.
    """

    anchor: str = ""
    text: str = ""
    kind: str = field(default="InsertAfter", init=False)

    def apply(self, content: str) -> str:
        idx = content.find(self.anchor)
        if not self.anchor or idx < 0:
            raise EditError(f"ancre introuvable: {self.anchor!r}")
        cut = idx + len(self.anchor)
        return content[:cut] + self.text + content[cut:]

    def cost(self) -> int:
        return len(self.anchor) + len(self.text)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "anchor": self.anchor, "text": self.text}


@dataclass
class DeleteRange(EditOp):
    """Supprime les caractères [start, end)."""

    start: int = 0
    end: int = 0
    kind: str = field(default="DeleteRange", init=False)

    def apply(self, content: str) -> str:
        if not (0 <= self.start <= self.end <= len(content)):
            raise EditError(f"bornes invalides: [{self.start}, {self.end}) sur {len(content)}")
        return content[: self.start] + content[self.end :]

    def cost(self) -> int:
        # deux entiers ~ 10 caractères, indépendant de la taille supprimée
        return len(str(self.start)) + len(str(self.end))

    def to_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start, "end": self.end}


@dataclass
class ReplaceRange(EditOp):
    """Remplace les caractères [start, end) par `text` — ancrage POSITIONNEL.

    Indispensable quand le même code se répète : `except Exception:\\n    pass` présent
    7 fois dans un fichier n'offre aucune ancre unique, ce qui fait échouer Replace/
    InsertAfter et force une réécriture complète. Le coût ne dépend pas de l'unicité.
    """

    start: int = 0
    end: int = 0
    text: str = ""
    kind: str = field(default="ReplaceRange", init=False)

    def apply(self, content: str) -> str:
        if not (0 <= self.start <= self.end <= len(content)):
            raise EditError(f"bornes invalides: [{self.start}, {self.end}) sur {len(content)}")
        return content[: self.start] + self.text + content[self.end :]

    def cost(self) -> int:
        return len(str(self.start)) + len(str(self.end)) + len(self.text)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start, "end": self.end, "text": self.text}


@dataclass
class ReplaceSymbolBody(EditOp):
    """Remplace le corps d'un symbole (fonction/classe/méthode) résolu par le SymbolResolver.

    Coûteux (le nouveau corps entier doit être émis) — c'est le fallback quand aucune
    édition locale ne suffit. Sert de borne haute dans le scoring MCPT.
    """

    symbol: str = ""
    original_body: str = ""
    new_body: str = ""
    kind: str = field(default="ReplaceSymbolBody", init=False)

    def apply(self, content: str) -> str:
        if not self.original_body or self.original_body not in content:
            raise EditError(f"corps du symbole introuvable: {self.symbol!r}")
        return content.replace(self.original_body, self.new_body, 1)

    def cost(self) -> int:
        return len(self.symbol) + len(self.new_body)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "symbol": self.symbol, "new_body": self.new_body}


# ═══════════════════════════════════════════════════════════════════════════════
# PLAN — une suite d'opérations
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EditPlan:
    """Suite ordonnée d'opérations + traçabilité de la stratégie qui l'a produite."""

    ops: list = field(default_factory=list)
    strategy: str = "unknown"

    def apply(self, content: str) -> str:
        out = content
        for op in self.ops:
            out = op.apply(out)
        return out

    def cost(self) -> int:
        """Coût d'émission du plan (proxy tokens) — critère central du MCPT."""
        return sum(op.cost() for op in self.ops) + 12 * len(self.ops)

    def char_changes(self, original: str) -> int:
        try:
            modified = self.apply(original)
        except EditError:
            return len(original)
        sm = difflib.SequenceMatcher(None, original, modified)
        return sum(
            max(i2 - i1, j2 - j1)
            for tag, i1, i2, j1, j2 in sm.get_opcodes()
            if tag != "equal"
        )

    def line_changes(self, original: str) -> int:
        try:
            modified = self.apply(original)
        except EditError:
            return len(original.splitlines())
        diff = difflib.unified_diff(original.splitlines(), modified.splitlines(), n=0)
        return sum(1 for line in diff if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))

    def to_dict(self) -> dict:
        return {"strategy": self.strategy, "cost": self.cost(), "ops": [op.to_dict() for op in self.ops]}


# ═══════════════════════════════════════════════════════════════════════════════
# DÉRIVATION — original + cible → plan minimal (déterministe, 0 token)
# ═══════════════════════════════════════════════════════════════════════════════

def _shrink_anchor(content: str, start: int, end: int, min_len: int = 3) -> str:
    """Plus courte ancre finissant en `end` et unique dans `content`.

    Une ancre courte = moins de tokens à émettre. On refuse toute ancre ambiguë
    (plusieurs occurrences) : la primitive frapperait au mauvais endroit.
    """
    for size in range(min_len, (end - start) + 1):
        cand = content[end - size : end]
        if cand and content.count(cand) == 1:
            return cand
    return content[start:end]


def _char_opcodes(original: str, modified: str) -> list:
    """Opcodes caractère, en deux temps : lignes d'abord, caractères dans les blocs changés.

    Un `SequenceMatcher` caractère sur le fichier ENTIER est en O(n²) : sur un fichier de
    100 Ko il ne termine pas (constaté — le pipeline bloquait indéfiniment sur server.py).
    On diffe donc par lignes (peu nombreuses, rapide), puis on raffine au caractère
    seulement à l'intérieur des blocs modifiés, en remappant sur des offsets absolus.
    Résultat identique en finesse, sans le mur de complexité.
    """
    olines = original.splitlines(keepends=True)
    mlines = modified.splitlines(keepends=True)
    o_off, m_off = [], []
    acc = 0
    for l in olines:
        o_off.append(acc)
        acc += len(l)
    o_off.append(acc)
    acc = 0
    for l in mlines:
        m_off.append(acc)
        acc += len(l)
    m_off.append(acc)

    out: list = []
    lsm = difflib.SequenceMatcher(None, olines, mlines, autojunk=False)
    for tag, i1, i2, j1, j2 in lsm.get_opcodes():
        if tag == "equal":
            continue
        a_start, a_end = o_off[i1], o_off[i2]
        b_start, b_end = m_off[j1], m_off[j2]
        block_a, block_b = original[a_start:a_end], modified[b_start:b_end]
        # bloc raisonnable → raffinage caractère ; sinon on garde le bloc entier
        if len(block_a) + len(block_b) <= 4000:
            csm = difflib.SequenceMatcher(None, block_a, block_b, autojunk=False)
            for ctag, ci1, ci2, cj1, cj2 in csm.get_opcodes():
                if ctag == "equal":
                    continue
                out.append((ctag, a_start + ci1, a_start + ci2, b_start + cj1, b_start + cj2))
        else:
            out.append((tag, a_start, a_end, b_start, b_end))
    return out


def derive_ops(original: str, modified: str, symbol: str = "") -> list:
    """Retourne les plans candidats menant de `original` à `modified`.

    Chaque plan est une façon DIFFÉRENTE d'exprimer la même transformation.
    Le choix du gagnant est délégué au scoring (patch_optimizer / edit_planner) —
    ici on ne fait que produire l'espace des possibles, sans appel LLM.
    """
    if original == modified:
        return [EditPlan(ops=[], strategy="noop")]

    plans: list = []
    opcodes = _char_opcodes(original, modified)

    # ── Stratégie CHARACTER : pure insertion → InsertAfter (aucune destruction) ──
    if all(tag == "insert" for tag, *_ in opcodes) and opcodes:
        ops = []
        ok = True
        for _tag, i1, _i2, j1, j2 in opcodes:
            anchor = _shrink_anchor(original, max(0, i1 - 40), i1)
            if not anchor:
                ok = False
                break
            ops.append(InsertAfter(anchor=anchor, text=modified[j1:j2]))
        if ok and ops:
            plans.append(EditPlan(ops=ops, strategy="character"))

    # ── Stratégie CHARACTER (bis) : pure suppression → DeleteRange ──────────────
    # Coût indexé (deux entiers), indépendant de la taille supprimée : c'est
    # toujours la façon la moins chère d'exprimer un retrait de code.
    if all(tag == "delete" for tag, *_ in opcodes) and opcodes:
        ops = [
            DeleteRange(start=i1, end=i2)
            for _tag, i1, i2, _j1, _j2 in sorted(opcodes, key=lambda oc: oc[1], reverse=True)
        ]
        plans.append(EditPlan(ops=ops, strategy="character"))

    # ── Stratégie TOKEN : remplacements locaux ancrés, un par hunk ──────────────
    ops = []
    ok = True
    for _tag, i1, i2, j1, j2 in opcodes:
        old = original[i1:i2]
        new = modified[j1:j2]
        if old and original.count(old) == 1:
            ops.append(Replace(anchor=old, replacement=new))
        else:
            # ancre élargie vers la gauche jusqu'à l'unicité
            lo = i1
            while lo > 0 and original.count(original[lo:i2]) != 1 and i1 - lo < 80:
                lo -= 1
            widened = original[lo:i2]
            if widened and original.count(widened) == 1:
                ops.append(Replace(anchor=widened, replacement=original[lo:i1] + new))
            else:
                ok = False
                break
    if ok and ops:
        plans.append(EditPlan(ops=ops, strategy="token"))

    # ── Stratégie OFFSET : ancrage positionnel, immunisé à la répétition ────────
    # Seule stratégie qui tient quand le même motif revient N fois (aucune ancre
    # textuelle n'est alors unique). Ops appliquées de droite à gauche pour que les
    # index restent valides.
    ops = [
        ReplaceRange(start=i1, end=i2, text=modified[j1:j2])
        for _tag, i1, i2, j1, j2 in sorted(opcodes, key=lambda oc: oc[1], reverse=True)
    ]
    if ops:
        plans.append(EditPlan(ops=ops, strategy="offset"))

    # ── Stratégie STATEMENT : remplacer les lignes touchées, entières ───────────
    olines = original.splitlines(keepends=True)
    mlines = modified.splitlines(keepends=True)
    lsm = difflib.SequenceMatcher(None, olines, mlines, autojunk=False)
    lops = []
    ok = True
    for tag, i1, i2, j1, j2 in lsm.get_opcodes():
        if tag == "equal":
            continue
        old_block = "".join(olines[i1:i2])
        new_block = "".join(mlines[j1:j2])
        if old_block and original.count(old_block) == 1:
            lops.append(Replace(anchor=old_block, replacement=new_block))
        elif not old_block:
            anchor = "".join(olines[max(0, i1 - 1) : i1])
            if anchor and original.count(anchor) == 1:
                lops.append(InsertAfter(anchor=anchor, text=new_block))
            else:
                ok = False
                break
        else:
            ok = False
            break
    if ok and lops:
        plans.append(EditPlan(ops=lops, strategy="statement"))

    # ── Stratégie SEMANTIC : borne haute — réécriture du corps du symbole ───────
    if symbol:
        plans.append(
            EditPlan(
                ops=[ReplaceSymbolBody(symbol=symbol, original_body=original, new_body=modified)],
                strategy="semantic",
            )
        )

    # ── Fallback : toujours au moins un plan applicable ─────────────────────────
    if not plans:
        plans.append(
            EditPlan(
                ops=[ReplaceSymbolBody(symbol=symbol or "file", original_body=original, new_body=modified)],
                strategy="semantic",
            )
        )

    # On ne garde que les plans qui reproduisent EXACTEMENT la cible.
    return [p for p in plans if _verifies(p, original, modified)]


def _verifies(plan: EditPlan, original: str, modified: str) -> bool:
    try:
        return plan.apply(original) == modified
    except EditError:
        return False


if __name__ == "__main__":  # pragma: no cover
    orig = "function guard(user) {\n  if (user) {\n    return allow();\n  }\n}\n"
    target = "function guard(user) {\n  if (user && user.isActive) {\n    return allow();\n  }\n}\n"
    for p in sorted(derive_ops(orig, target, symbol="guard"), key=lambda x: x.cost()):
        print(f"{p.strategy:<10} cost={p.cost():<5} chars={p.char_changes(orig):<4} ops={p.to_dict()['ops']}")
