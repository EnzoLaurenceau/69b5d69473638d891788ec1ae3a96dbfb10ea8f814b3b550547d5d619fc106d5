"""
forge_fingerprint.py — Execution Fingerprint + Zero-Redundancy Gate
====================================================================
Vague AAOS (09_TASKS/aaos_devops_plan.md) — items 63, 64, 65, 78, 79, 87.

  63  Execution fingerprint : hash(task+context+tier+version) → résultat persisté
  64  Zero-redundancy       : même empreinte dans le TTL → 0 appel LLM
  65  Context deduplication : dedupe_chunks() par hash exact
  78  Replacement engine    : tâche répétée ≥ N fois → candidate script/outil
  79  Task classifier       : score déterministe (0 token) requires_reasoning/
                              can_be_scripted/can_be_cached/can_run_locally
  87  Cost comparison       : route recommandée cache/script/free/llm

Intégration : forge_llm.forge_call() consulte check() AVANT tout appel
(tous tiers, pas seulement FREE) et record() après. Kill switch :
env FORGE_FINGERPRINT_OFF=1.

Persistance : 05_STATE/execution_fingerprints.json (JSON lisible, 1000 max).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import datetime
from pathlib import Path
from typing import Optional
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

FORGE_ROOT = Path(__file__).parent.parent.parent


def FP_STORE_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("execution_fingerprints.json")


TTL_SECONDS = 7 * 86400          # 7 jours — au-delà, une empreinte est périmée
MAX_ENTRIES = 1000               # cap disque
MAX_RESULT_CHARS = 20_000        # on ne cache pas les résultats géants
REPEAT_THRESHOLD = 3             # tâche vue N fois → candidate remplacement script
AGENTS_VERSION = "v1"            # bump manuel si les prompts agents changent (invalide tout)


# ─── 63 — Fingerprint ─────────────────────────────────────────────────────────

def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8", errors="replace")).hexdigest()


def make_fingerprint(prompt: str, system: str = "", tier: str = "",
                     task_type: str = "", agents_version: str = AGENTS_VERSION) -> str:
    """Empreinte déterministe d'une exécution : même tâche + même contexte
    + même version d'agents → même hash."""
    return _sha(prompt.strip(), system.strip(), tier, task_type, agents_version)


# ─── 65 — Context deduplication ───────────────────────────────────────────────

def dedupe_chunks(chunks: list[str]) -> list[str]:
    """Supprime les chunks strictement identiques (hash exact), ordre préservé."""
    seen: set[str] = set()
    out: list[str] = []
    for c in chunks:
        h = _sha(c.strip())
        if h not in seen:
            seen.add(h)
            out.append(c)
    return out


# ─── 79 — Task classifier (déterministe, 0 token) ───────────────────────────

# Radicaux volontairement sans \b final (conçoi→conçois, extrai→extraire…)
_REASONING_PAT = re.compile(
    r"\b(pourquoi|architect|conçoi|design|stratég|strategy|plan\b|analyse approfondie|"
    r"trade-?off|arbitrage|décide|évalue|creative|créatif|brainstorm)", re.I)
_SCRIPTABLE_PAT = re.compile(
    r"\b(extract|extrai|parse|count|compte|convert|converti|format|rename|renomme|"
    r"csv|regex|somme|sum|trie|sort|filtre|filter|dédup|dedup|hash|diff)", re.I)
_TOKEN_ID_PAT = re.compile(r"^\d+#\d+:")   # protocole Token-ID du cervelet


def classify_task(prompt: str) -> dict:
    """Score déterministe d'une tâche AVANT tout appel LLM (item 79)."""
    p = prompt.strip()
    is_token_id = bool(_TOKEN_ID_PAT.match(p))
    scriptable = is_token_id or bool(_SCRIPTABLE_PAT.search(p))
    reasoning = (not is_token_id) and (bool(_REASONING_PAT.search(p)) or len(p) > 4000)
    est_tokens = max(1, len(p) // 4)
    return {
        "requires_reasoning": reasoning,
        "can_be_scripted": scriptable and not reasoning,
        "can_be_cached": True,
        "can_run_locally": is_token_id or (scriptable and not reasoning),
        "estimated_token_cost": round(est_tokens / 1_000_000 * 3.0, 6),  # ~prix sonnet input
        "estimated_local_cost": 0.0001,
    }


# ─── Store (63/64/78) ─────────────────────────────────────────────────────────

class FingerprintStore:
    """Journal persistant des exécutions, consulté avant chaque appel LLM."""

    def __init__(self, path: Path = FP_STORE_PATH()):
        self._path = path
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._entries = json.loads(self._path.read_text(encoding="utf-8")).get("entries", {})
            except Exception:
                self._entries = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if len(self._entries) > MAX_ENTRIES:
            # évince les plus anciennes (par dernier accès)
            ordered = sorted(self._entries.items(), key=lambda kv: kv[1].get("last_used", 0))
            self._entries = dict(ordered[-MAX_ENTRIES:])
        self._path.write_text(
            json.dumps({"entries": self._entries,
                        "last_updated": datetime.datetime.now().isoformat()},
                       ensure_ascii=False), encoding="utf-8")

    # ── 64 — Zero-redundancy gate ────────────────────────────────────────────
    def check(self, fp: str) -> Optional[dict]:
        """Retourne l'entrée si empreinte connue et non périmée, sinon None."""
        e = self._entries.get(fp)
        if not e:
            return None
        if time.time() - e.get("created", 0) > TTL_SECONDS:
            self._entries.pop(fp, None)
            return None
        e["hits"] = e.get("hits", 0) + 1
        e["last_used"] = time.time()
        self._save()
        return e

    def record(self, fp: str, result: str, provider: str = "", cost: float = 0.0,
               latency: float = 0.0, tokens: int = 0, task: str = "",
               task_type: str = "") -> None:
        """Item 63 : enregistre l'exécution complète."""
        if not result or result.startswith("ERR") or len(result) > MAX_RESULT_CHARS:
            return
        self._entries[fp] = {
            "task_hash": fp,
            "task": task[:200],
            "task_type": task_type,
            "result": result,
            "result_hash": _sha(result),
            "provider": provider,
            "version": AGENTS_VERSION,
            "cost": cost,
            "latency": latency,
            "tokens": tokens,
            "hits": self._entries.get(fp, {}).get("hits", 0),
            "created": time.time(),
            "last_used": time.time(),
        }
        self._save()

    # ── 78 — Replacement engine ──────────────────────────────────────────────
    def detect_repetitive(self, threshold: int = REPEAT_THRESHOLD) -> list[dict]:
        """Tâches ré-exécutées ≥ threshold fois → candidates à un remplacement
        script/outil (le LLM ne devrait plus les faire)."""
        out = []
        for e in self._entries.values():
            if e.get("hits", 0) >= threshold:
                cls = classify_task(e.get("task", ""))
                out.append({
                    "task": e.get("task", ""),
                    "task_type": e.get("task_type", ""),
                    "hits": e["hits"],
                    "tokens_wasted_estimate": e.get("tokens", 0) * e["hits"],
                    "can_be_scripted": cls["can_be_scripted"],
                    "recommendation": ("écrire un wrapper/script (règle #5 DO NOT INVENT)"
                                       if cls["can_be_scripted"]
                                       else "cache hit couvre déjà — surveiller"),
                })
        return sorted(out, key=lambda x: x["hits"], reverse=True)

    def stats(self) -> dict:
        total_hits = sum(e.get("hits", 0) for e in self._entries.values())
        return {
            "entries": len(self._entries),
            "total_cache_hits": total_hits,
            "tokens_saved_estimate": sum(e.get("tokens", 0) * e.get("hits", 0)
                                         for e in self._entries.values()),
            "repetitive_candidates": len(self.detect_repetitive()),
        }


# ─── 87 — Cost comparison engine ─────────────────────────────────────────────

def compare_costs(prompt: str, system: str = "", tier: str = "",
                  task_type: str = "") -> dict:
    """Compare cache / script local / LLM et recommande la route la moins chère
    à qualité suffisante (item 87). Déterministe, 0 token."""
    cls = classify_task(prompt)
    fp = make_fingerprint(prompt, system, tier, task_type)
    cached = get_fingerprint_store().check(fp) is not None
    if cached:
        route = "cache"
    elif cls["can_run_locally"]:
        route = "local"       # cervelet réflexe ou script
    elif not cls["requires_reasoning"]:
        route = "free_llm"    # tier FREE suffit
    else:
        route = "llm"
    return {"route": route, "fingerprint": fp, "classification": cls,
            "llm_cost": cls["estimated_token_cost"],
            "local_cost": cls["estimated_local_cost"],
            "cache_cost": 0.0}


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[FingerprintStore] = None


def get_fingerprint_store() -> FingerprintStore:
    global _store
    if _store is None:
        _store = FingerprintStore()
    return _store


def fingerprint_enabled() -> bool:
    return os.environ.get("FORGE_FINGERPRINT_OFF", "") not in ("1", "true", "yes")


# ─── Self-check ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "fp.json"
    s = FingerprintStore(tmp)

    # 63/64 — record puis hit, miss sur variante
    fp1 = make_fingerprint("extract emails from log", "", "free", "fast_extraction")
    assert s.check(fp1) is None
    s.record(fp1, "a@b.com", provider="free", tokens=120, latency=0.8,
             task="extract emails from log", task_type="fast_extraction")
    hit = s.check(fp1)
    assert hit and hit["result"] == "a@b.com" and hit["hits"] == 1
    assert s.check(make_fingerprint("extract emails from log2", "", "free", "")) is None
    # résultat erreur jamais caché
    fp_err = make_fingerprint("x", "", "free", "")
    s.record(fp_err, "ERR:boom")
    assert s.check(fp_err) is None

    # 65 — dedup
    assert dedupe_chunks(["a", "b", "a", " a "]) == ["a", "b"]

    # 79 — classifier
    c1 = classify_task("extract all emails and count duplicates in this csv")
    assert c1["can_be_scripted"] and not c1["requires_reasoning"]
    c2 = classify_task("conçois l'architecture microservices et évalue les options de trade-off")
    assert c2["requires_reasoning"] and not c2["can_be_scripted"]
    assert classify_task("200#10:3500,1200")["can_run_locally"]

    # 78 — répétition
    s.check(fp1); s.check(fp1)
    reps = s.detect_repetitive(threshold=3)
    assert reps and reps[0]["hits"] >= 3

    # 87 — cost comparison (store global séparé : route sans cache)
    r = compare_costs("compte les lignes du fichier csv")
    assert r["route"] in ("local", "cache")
    r2 = compare_costs("conçois la stratégie produit et évalue les options")
    assert r2["route"] in ("llm", "cache")

    print("forge_fingerprint self-check: OK")
    print(json.dumps(s.stats(), indent=2))
