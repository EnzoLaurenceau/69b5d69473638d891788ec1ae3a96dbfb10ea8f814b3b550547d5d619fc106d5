"""patch_optimizer.py — sélection du patch de coût minimal (MCPT).

Principe : le LLM ne produit PAS le patch, il produit l'INTENTION (le code cible).
Le moteur dérive ensuite, de façon déterministe et sans token, toutes les façons
d'exprimer cette transformation (character / token / statement / semantic), les
score, et retient la moins coûteuse qui reste sûre.

    coût_MCPT = f(tokens émis, caractères modifiés, lignes touchées, risque syntaxique)

Deux modes :
  - `modified_code` fourni  → 100 % déterministe, 0 token (mode privilégié).
  - `modified_code` absent  → un appel `forge_call` (tier FREE, règle ANTI-DÉRIVE)
    demande le code cible ; si indisponible → retourne None, jamais d'invention.

Self-check : python -m forge_agents.semantic_edit_engine.patch_optimizer
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .edit_primitives import EditPlan, derive_ops

logger = logging.getLogger(__name__)

# Poids du coût composite. `emit` domine : c'est lui qui paie les tokens.
COST_WEIGHTS = {"emit": 1.0, "chars": 0.5, "lines": 4.0, "ops": 8.0}


class PatchStrategy(Enum):
    CHARACTER = "character"
    TOKEN = "token"
    OFFSET = "offset"
    STATEMENT = "statement"
    SEMANTIC = "semantic"
    NOOP = "noop"


@dataclass
class PatchCandidate:
    strategy: PatchStrategy
    original: str
    modified: str
    target_name: str
    file_path: str
    diff: str
    plan: Optional[EditPlan] = None
    ast_changes: int = 0
    char_changes: int = 0
    token_changes: int = 0
    line_changes: int = 0
    emit_cost: int = 0          # caractères que le LLM doit émettre pour ce plan
    mcpt_cost: float = 0.0      # coût composite — critère de sélection
    score: float = 0.0          # qualité PatchScorer (0-1), critère de sûreté

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "target": self.target_name,
            "file": self.file_path,
            "emit_cost": self.emit_cost,
            "mcpt_cost": round(self.mcpt_cost, 2),
            "score": round(self.score, 4),
            "char_changes": self.char_changes,
            "line_changes": self.line_changes,
            "ops": self.plan.to_dict()["ops"] if self.plan else [],
        }


class SemanticPatchOptimizer:
    """Génère les plans candidats, les score, retient le coût minimal sûr."""

    #: en dessous de ce score PatchScorer, un plan est écarté même s'il est moins cher
    SAFETY_FLOOR = 0.55

    def __init__(self, weights: dict | None = None):
        self.weights = weights or COST_WEIGHTS

    # ── API principale ─────────────────────────────────────────────────────────
    def optimize(
        self,
        instruction: str,
        file_path: Path,
        target_name: str = None,
        modified_code: str = None,
    ) -> Optional[PatchCandidate]:
        file_path = Path(file_path)
        if not file_path.exists():
            logger.warning("patch_optimizer: fichier absent %s", file_path)
            return None

        content = file_path.read_text(encoding="utf-8")

        from .symbol_resolver import get_symbol_resolver

        target = None
        if target_name:
            try:
                target = get_symbol_resolver().resolve(target_name, file_path)
            except Exception as exc:  # résolution best-effort, jamais bloquante
                logger.debug("symbol_resolver KO sur %s: %s", target_name, exc)

        orig_code = getattr(target, "source_text", None) or content
        tname = target_name or "file"

        if modified_code is None:
            modified_code = self._llm_target(instruction, orig_code, file_path)
        if modified_code is None:
            logger.warning("patch_optimizer: pas de code cible pour %r — abandon", instruction)
            return None
        # `symbol_resolver` rend le corps du symbole sans son saut de ligne final :
        # comparer brut produirait un patch fantôme d'un caractère quand la cible
        # est en réalité identique. On neutralise ce bruit de bordure.
        if modified_code.rstrip() == orig_code.rstrip():
            logger.info("patch_optimizer: cible identique à l'original (hors bordure) — noop")
            return None

        candidates = self.candidates(orig_code, modified_code, file_path, tname)
        if not candidates:
            return None
        return candidates[0]

    def candidates(
        self, orig_code: str, modified_code: str, file_path: Path, target_name: str = "file"
    ) -> list:
        """Tous les plans applicables, triés du moins cher au plus cher."""
        from .patch_scorer import PatchScorer

        scorer = PatchScorer()
        plans = derive_ops(orig_code, modified_code, symbol=target_name)
        out: list = []

        for plan in plans:
            emit = plan.cost()
            chars = plan.char_changes(orig_code)
            lines = plan.line_changes(orig_code)
            mcpt = (
                self.weights["emit"] * emit
                + self.weights["chars"] * chars
                + self.weights["lines"] * lines
                + self.weights["ops"] * len(plan.ops)
            )
            score_obj = scorer.score(
                orig_code,
                modified_code,
                file_path,
                tokens_before=max(len(orig_code) // 4, 1),
                tokens_after=max(emit // 4, 1),
            )
            try:
                strategy = PatchStrategy(plan.strategy)
            except ValueError:
                strategy = PatchStrategy.SEMANTIC

            out.append(
                PatchCandidate(
                    strategy=strategy,
                    original=orig_code,
                    modified=modified_code,
                    target_name=target_name,
                    file_path=str(file_path),
                    diff="\n".join(
                        difflib.unified_diff(
                            orig_code.splitlines(), modified_code.splitlines(), lineterm=""
                        )
                    ),
                    plan=plan,
                    char_changes=chars,
                    line_changes=lines,
                    token_changes=max(emit // 4, 0),
                    emit_cost=emit,
                    mcpt_cost=mcpt,
                    score=score_obj.global_score,
                )
            )

        safe = [c for c in out if c.score >= self.SAFETY_FLOOR]
        pool = safe or out  # aucun plan sûr → on renvoie quand même, l'appelant tranche
        return sorted(pool, key=lambda c: (c.mcpt_cost, -c.score))

    # ── Génération de la cible (dernier recours, tier FREE) ────────────────────
    # Seuil : si le LLM supprime plus de 20 % des lignes, on rejette — probable
    # hallucination de suppression (le prompt dit "change le minimum" mais le modèle
    # omet des lignes non-modifiées). Un ajout excessif (>50 %) est aussi suspect.
    _LLM_LINE_SHRINK_LIMIT = 0.20
    _LLM_LINE_GROW_LIMIT = 0.50

    @staticmethod
    def _llm_target(instruction: str, orig_code: str, file_path: Path) -> Optional[str]:
        """Demande le code cible au LLM. Dégradation gracieuse : None si indisponible."""
        try:
            from ..forge_llm import forge_call  # import tardif : évite un cycle
        except Exception as exc:
            logger.debug("forge_llm indisponible: %s", exc)
            return None

        orig_lines = len(orig_code.splitlines())
        prompt = (
            f"Fichier: {file_path.name}\n"
            f"Instruction: {instruction}\n\n"
            "IMPORTANT : renvoie le fichier COMPLET avec la modification appliquée.\n"
            "Ne supprime AUCUNE ligne non concernée par l'instruction.\n"
            "Change le strict minimum de mots. Préserve l'indentation, le style,\n"
            "et TOUTES les lignes qui ne sont pas visées par le changement.\n"
            "Pas de commentaire, pas de bloc markdown — le code source uniquement.\n\n"
            f"--- CODE ({orig_lines} lignes) ---\n{orig_code}"
        )
        try:
            raw = forge_call(prompt)
        except Exception as exc:
            logger.warning("forge_call KO: %s", exc)
            return None

        text = raw if isinstance(raw, str) else str(getattr(raw, "content", "") or raw)
        text = text.strip()
        if not text:
            return None
        # Strip markdown fences (greedy to handle nested ```)
        fence = re.match(r"^```[a-zA-Z0-9_+-]*\n(.*?)\n```$", text, flags=re.DOTALL)
        if fence:
            text = fence.group(1).rstrip("\n")

        # ── Validation : le LLM ne doit pas supprimer massivement des lignes ──
        new_lines = len(text.splitlines())
        if orig_lines >= 4:  # fichiers trop courts → pas de validation
            if new_lines < orig_lines * (1 - SemanticPatchOptimizer._LLM_LINE_SHRINK_LIMIT):
                logger.warning(
                    "_llm_target: réponse rejetée — %d lignes vs %d originales "
                    "(shrink %.0f%% > seuil %.0f%%). LLM a probablement omis des lignes.",
                    new_lines, orig_lines,
                    (1 - new_lines / orig_lines) * 100,
                    SemanticPatchOptimizer._LLM_LINE_SHRINK_LIMIT * 100,
                )
                return None
            if new_lines > orig_lines * (1 + SemanticPatchOptimizer._LLM_LINE_GROW_LIMIT):
                logger.warning(
                    "_llm_target: réponse rejetée — %d lignes vs %d originales "
                    "(grow %.0f%% > seuil %.0f%%). LLM a probablement ajouté du bruit.",
                    new_lines, orig_lines,
                    (new_lines / orig_lines - 1) * 100,
                    SemanticPatchOptimizer._LLM_LINE_GROW_LIMIT * 100,
                )
                return None

        return text


_optimizer = SemanticPatchOptimizer()


def get_patch_optimizer() -> SemanticPatchOptimizer:
    return _optimizer


def optimize_patch(
    instruction: str, file_path: Path, target_name: str = None, modified_code: str = None
) -> Optional[PatchCandidate]:
    return get_patch_optimizer().optimize(instruction, file_path, target_name, modified_code)


if __name__ == "__main__":  # pragma: no cover
    import tempfile

    src = "def guard(user):\n    if user:\n        return allow()\n    return deny()\n"
    tgt = "def guard(user):\n    if user and user.is_active:\n        return allow()\n    return deny()\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(src)
        tmp = Path(fh.name)

    opt = get_patch_optimizer()
    for cand in opt.candidates(src, tgt, tmp, "guard"):
        print(
            f"{cand.strategy.value:<10} mcpt={cand.mcpt_cost:<7.1f} emit={cand.emit_cost:<4} "
            f"lines={cand.line_changes} score={cand.score:.3f}"
        )
    best = opt.candidates(src, tgt, tmp, "guard")[0]
    print("\nGAGNANT:", best.to_dict()["ops"])
    assert best.plan.apply(src) == tgt, "le plan gagnant ne reproduit pas la cible"
    print("OK — plan vérifié")
    tmp.unlink(missing_ok=True)
