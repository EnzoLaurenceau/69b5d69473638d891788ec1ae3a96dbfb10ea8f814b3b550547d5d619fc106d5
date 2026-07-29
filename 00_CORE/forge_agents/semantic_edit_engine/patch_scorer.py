from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from pathlib import Path
import difflib

logger = logging.getLogger(__name__)

@dataclass
class ScoringWeights:
    minimal_edit: float = 0.25
    compilation: float = 0.30
    semantic_safety: float = 0.20
    formatting: float = 0.10
    git_diff: float = 0.10
    token_efficiency: float = 0.05

@dataclass
class PatchScore:
    minimal_edit: float
    compilation: float
    semantic_safety: float
    formatting: float
    git_diff: float
    token_efficiency: float
    weights: ScoringWeights

    @property
    def global_score(self) -> float:
        return (
            self.minimal_edit * self.weights.minimal_edit +
            self.compilation * self.weights.compilation +
            self.semantic_safety * self.weights.semantic_safety +
            self.formatting * self.weights.formatting +
            self.git_diff * self.weights.git_diff +
            self.token_efficiency * self.weights.token_efficiency
        )

    def to_dict(self) -> dict:
        return {
            "minimal_edit": self.minimal_edit,
            "compilation": self.compilation,
            "semantic_safety": self.semantic_safety,
            "formatting": self.formatting,
            "git_diff": self.git_diff,
            "token_efficiency": self.token_efficiency,
            "global_score": self.global_score
        }

    def to_nmp(self) -> str:
        return f"SCORE|SEE|EVAL|global={self.global_score:.4f}"

class PatchScorer:
    def __init__(self, weights: ScoringWeights = None):
        self.weights = weights or ScoringWeights()

    def score_minimal_edit(self, original: str, modified: str) -> float:
        s = difflib.SequenceMatcher(None, original, modified)
        return s.ratio()

    def score_compilation(self, file_path: Path, content: str) -> float:
        if file_path.suffix == ".py":
            try:
                compile(content, file_path.name, "exec")
                return 1.0
            except Exception:
                return 0.0
        return 1.0

    def score_semantic_safety(self, original: str, modified: str) -> float:
        def clean(t):
            t = re.sub(r'#.*', '', t)
            t = re.sub(r'""".*?"""', '', t, flags=re.DOTALL)
            t = re.sub(r"'''.*?'''", '', t, flags=re.DOTALL)
            return "".join(t.split())
        c_orig = clean(original)
        c_mod = clean(modified)
        s = difflib.SequenceMatcher(None, c_orig, c_mod)
        return s.ratio()

    def score_formatting(self, original: str, modified: str) -> float:
        orig_tabs = '\t' in original
        mod_tabs = '\t' in modified
        if orig_tabs != mod_tabs:
            return 0.5
        return 1.0

    def score_git_diff(self, original: str, modified: str) -> float:
        lines_orig = original.splitlines()
        lines_mod = modified.splitlines()
        diff = list(difflib.unified_diff(lines_orig, lines_mod))
        diff_lines = len(diff)
        total_lines = max(len(lines_orig), 1)
        return max(0.0, 1.0 - (diff_lines / total_lines))

    def score_token_efficiency(self, context_tokens_before: int, context_tokens_after: int) -> float:
        if context_tokens_before <= 0:
            return 1.0
        return min(1.0, max(0.0, 1.0 - (context_tokens_after / context_tokens_before)))

    def score(self, original: str, modified: str, file_path: Path, tokens_before: int = 1, tokens_after: int = 1) -> PatchScore:
        return PatchScore(
            minimal_edit=self.score_minimal_edit(original, modified),
            compilation=self.score_compilation(file_path, modified),
            semantic_safety=self.score_semantic_safety(original, modified),
            formatting=self.score_formatting(original, modified),
            git_diff=self.score_git_diff(original, modified),
            token_efficiency=self.score_token_efficiency(tokens_before, tokens_after),
            weights=self.weights
        )
