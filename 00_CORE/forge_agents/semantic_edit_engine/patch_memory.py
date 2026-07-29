from __future__ import annotations
import logging
import json
import uuid
import datetime
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent.parent

@dataclass
class PatchRecord:
    patch_id: str
    strategy: str
    language: str
    symbol_kind: str
    symbol_name: str
    file_path: str
    success: bool
    score: float
    compilation_ok: bool
    tests_ok: bool
    rolled_back: bool
    git_conflict: bool
    time_ms: float
    tokens_used: int
    patch_size_lines: int
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    def to_nmp(self) -> str:
        return f"PATCH|MEMORY|RECORD|strategy={self.strategy},lang={self.language},score={self.score:.2f},success={self.success}"

    @staticmethod
    def from_dict(d: dict) -> PatchRecord:
        return PatchRecord(**d)

def _default_storage_path() -> Path:
    try:
        from ..forge_store import state_path
    except ImportError:
        from forge_agents.forge_store import state_path
    return state_path("patch_memory.json")


class PatchMemory:
    def __init__(self, storage_path: Path = None):
        # Cloisonné par tenant (W5-03c) : sans chemin injecté, le défaut est résolu à
        # l'appel via forge_store (les patchs appartiennent au dépôt du client). Sans
        # tenant en contexte → repli GLOBAL historique (05_STATE/patch_memory.json).
        self.storage_path = storage_path or _default_storage_path()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.records: list[PatchRecord] = []
        self._load()

    def _load(self):
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                self.records = [PatchRecord.from_dict(d) for d in data]
            except Exception as e:
                logger.error(f"PATCH_MEMORY|LOAD_FAIL|err={e}")

    def _save(self):
        try:
            data = [r.to_dict() for r in self.records]
            self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"PATCH_MEMORY|SAVE_FAIL|err={e}")

    def record(self, record: PatchRecord):
        self.records.append(record)
        self._save()
        try:
            from ..graphify_checkpointer import graphify_index
            if graphify_index:
                graphify_index(record.to_nmp())
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def best_strategy(self, language: str, symbol_kind: str = None) -> str:
        strategy_scores: dict[str, list[float]] = {}
        for r in self.records:
            if r.language.lower() == language.lower():
                strategy_scores.setdefault(r.strategy, []).append(r.score)
        
        if not strategy_scores:
            return "statement"
        
        best = max(strategy_scores.items(), key=lambda item: sum(item[1]) / len(item[1]))
        return best[0]

    def get_stats(self) -> dict:
        total = len(self.records)
        if total == 0:
            return {"total_patches": 0, "success_rate": 0.0}
        successes = sum(1 for r in self.records if r.success)
        return {
            "total_patches": total,
            "success_rate": successes / total,
            "rollback_rate": sum(1 for r in self.records if r.rolled_back) / total
        }

_memory = PatchMemory()

def get_patch_memory() -> PatchMemory:
    return _memory
