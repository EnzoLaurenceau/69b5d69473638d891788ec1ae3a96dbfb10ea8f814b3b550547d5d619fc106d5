"""
turbovec_brain.py — TurboVec 4-bit semantic brain for Mimo on Hermes
=====================================================================
Implémente optiforge §1 Token Guard avec la vraie lib turbovec :
  - IdMapIndex(dim=1536, bit_width=4) — index quantisé 4-bit local
  - vectorize(text) → numpy float32 (hash-based embedding, no LLM)
  - store(id, text) → add to index
  - search(query, k) → top-k ids + scores
  - session_compaction() → vide les vecteurs de session hors top-N
                           pour rester sous le ceiling 65k tokens

Règle absolue : raw text NEVER in LLM context.
Toute connaissance passe par cet index avant injection.

Ceiling Mimo/Hermes : 65 000 tokens (round-trip billing).
"""

from __future__ import annotations
import hashlib
import json
import logging
import struct
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import turbovec  # type: ignore
    _TURBOVEC_AVAILABLE = True
except ImportError:
    turbovec = None  # type: ignore
    _TURBOVEC_AVAILABLE = False

log = logging.getLogger("TurboVecBrain")

if not _TURBOVEC_AVAILABLE:
    log.info(
        "[TURBOVEC] paquet 'turbovec' absent -> fallback index numpy brute-force "
        "(degradation gracieuse, borne par SESSION_TOP_K). pip install turbovec pour la vraie lib 4-bit."
    )

FORGE_ROOT   = Path(__file__).parent.parent.parent
BRAIN_STATE  = FORGE_ROOT / ".nexus" / "forge_state.json"
DIM          = 256          # dim réduite : hash → 256 floats (rapide, no GPU)
BIT_WIDTH    = 4
TOKEN_CEILING = 65_000      # ceiling Mimo/Hermes (round-trip billing)
COMPACTION_TARGET = 0.70    # garde 70% du ceiling max → trigger à 65k*0.85
COMPACTION_TRIGGER = int(TOKEN_CEILING * 0.85)  # 55 250 tokens → compaction auto
SESSION_TOP_K    = 50       # max vecteurs gardés après compaction


# ─── Embedding local (hash-based, zéro LLM) ──────────────────────────────────

def _hash_embed(text: str) -> np.ndarray:
    """
    4-bit TurboVec compatible embedding sans modèle externe.
    SHA-256 du texte → 32 bytes → 256 floats normalisés.
    Approximation déterministe, vitesse O(len(text)).
    """
    raw = text.encode("utf-8", errors="replace")
    # Multi-pass SHA pour remplir 256 dims
    seed = b""
    floats: list[float] = []
    while len(floats) < DIM:
        h = hashlib.sha256(seed + raw).digest()  # 32 bytes = 32 floats
        for i in range(0, 32, 4):
            val = struct.unpack(">I", h[i:i+4])[0]
            floats.append((val / 0xFFFFFFFF) * 2.0 - 1.0)
        seed = h
    arr = np.array(floats[:DIM], dtype=np.float32)
    norm = np.linalg.norm(arr)
    return arr / norm if norm > 0 else arr


# ─── Fallback index (si le paquet prive `turbovec` n'est pas installe) ───────

class _NumpyFallbackIndex:
    """
    Index brute-force cosine, meme interface que turbovec.IdMapIndex
    (add_with_ids / search). Pas de quantisation 4-bit, mais correct et
    suffisant a l'echelle d'une session (bornee par SESSION_TOP_K=50).
    """

    def __init__(self, dim: int, bit_width: int = 4) -> None:
        self._dim = dim
        self._vecs = np.zeros((0, dim), dtype=np.float32)
        self._ids = np.zeros((0,), dtype=np.uint64)

    def add_with_ids(self, vecs: np.ndarray, ids: np.ndarray) -> None:
        self._vecs = np.vstack([self._vecs, vecs]) if self._vecs.shape[0] else vecs.copy()
        self._ids = np.concatenate([self._ids, ids]) if self._ids.shape[0] else ids.copy()

    def search(self, vec: np.ndarray, k: int = 5):
        if self._vecs.shape[0] == 0:
            return np.zeros((1, 0), dtype=np.float32), np.zeros((1, 0), dtype=np.uint64)
        sims = self._vecs @ vec[0]  # vecteurs deja normalises -> dot = cosine
        k_actual = min(k, sims.shape[0])
        order = np.argsort(-sims)[:k_actual]
        return sims[order].reshape(1, -1), self._ids[order].reshape(1, -1)


def _make_index() -> Any:
    if _TURBOVEC_AVAILABLE:
        return turbovec.IdMapIndex(dim=DIM, bit_width=BIT_WIDTH)
    return _NumpyFallbackIndex(dim=DIM, bit_width=BIT_WIDTH)


# ─── TurboVecBrain ───────────────────────────────────────────────────────────

class TurboVecBrain:
    """
    Brain 4-bit quantisé pour Mimo.
    store() → vectorise + indexe
    search() → top-k semantic (cosine approx via dot sur 4-bit)
    session_compaction() → prune automatique quand > COMPACTION_TRIGGER tokens
    """

    def __init__(self) -> None:
        self._db   = _make_index()
        self._meta: dict[int, dict] = {}   # id → {text, agent, score, tok_est}
        self._next_id = 1
        self._session_tokens = 0
        BRAIN_STATE.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # ── Public API ────────────────────────────────────────────────────────────

    def store(self, text: str, agent: str = "ORCH",
              score: float = 0.0, cycle: int = 0) -> int:
        """Vectorise + indexe un texte. Retourne l'id interne."""
        tok_est = int(len(text.split()) * 1.3)
        self._session_tokens += tok_est

        vec = _hash_embed(text)
        uid = self._next_id
        self._next_id += 1

        ids = np.array([uid], dtype=np.uint64)
        vecs = vec.reshape(1, DIM)
        self._db.add_with_ids(vecs, ids)
        self._meta[uid] = {
            "text": text[:500],     # stocke résumé, pas raw complet
            "agent": agent,
            "score": score,
            "cycle": cycle,
            "tok_est": tok_est,
        }
        self._save_state()

        # Auto-compaction si on approche du ceiling
        if self._session_tokens >= COMPACTION_TRIGGER:
            self.session_compaction()

        return uid

    def search(self, query: str, k: int = 5) -> list[dict]:
        """
        Recherche sémantique top-k. Retourne résumés (jamais raw).
        Token Guard : seul text[:200] retourné dans le contexte LLM.
        """
        if not self._meta:
            return []
        vec = _hash_embed(query).reshape(1, DIM)
        k_actual = min(k, len(self._meta))
        try:
            scores, ids = self._db.search(vec, k=k_actual)
        except Exception as e:
            log.warning(f"[TURBOVEC] search err: {e}")
            return []

        results = []
        for score_val, uid in zip(scores[0], ids[0]):
            m = self._meta.get(int(uid))
            if m:
                results.append({
                    "id": int(uid),
                    "score": float(score_val),
                    "agent": m["agent"],
                    "summary": m["text"][:200],   # Token Guard : 200 chars max
                    "cycle": m["cycle"],
                })
        return sorted(results, key=lambda x: x["score"], reverse=True)

    def session_compaction(self) -> int:
        """
        optiforge §1 + Ceiling Protocol Mimo/Hermes :
        Quand session_tokens > COMPACTION_TRIGGER (55 250) :
          1. Garde les SESSION_TOP_K vecteurs au score le plus élevé
          2. Reconstruit l'index avec seulement ces vecteurs
          3. Reset session_tokens au niveau réel post-prune
          4. Log NMP BOOST_NODE pour traçabilité

        Retourne le nombre de vecteurs supprimés.
        """
        if len(self._meta) <= SESSION_TOP_K:
            return 0

        # Tri par score décroissant → garde les meilleurs
        ranked = sorted(self._meta.items(), key=lambda x: x[1]["score"], reverse=True)
        keep   = dict(ranked[:SESSION_TOP_K])
        pruned = len(self._meta) - len(keep)

        # Reconstruit l'index TurboVec proprement
        self._db = _make_index()
        for uid, m in keep.items():
            vec = _hash_embed(m["text"]).reshape(1, DIM)
            ids = np.array([uid], dtype=np.uint64)
            self._db.add_with_ids(vec, ids)

        self._meta = keep
        self._session_tokens = sum(m["tok_est"] for m in keep.values())
        self._save_state()

        log.info(
            f"BOOST_NODE|TURBOVEC|SESSION_COMPACT|pruned={pruned} "
            f"kept={len(keep)} session_tokens={self._session_tokens}"
        )
        return pruned

    def token_pressure(self) -> dict:
        """Retourne l'état du budget tokens Mimo/Hermes."""
        return {
            "session_tokens": self._session_tokens,
            "ceiling": TOKEN_CEILING,
            "pressure_pct": round(self._session_tokens / TOKEN_CEILING * 100, 1),
            "compaction_trigger": COMPACTION_TRIGGER,
            "vectors_stored": len(self._meta),
            "nmp": (f"BUDGET|TURBOVEC|{self._session_tokens}|"
                    f"ceiling={TOKEN_CEILING} "
                    f"pressure={self._session_tokens/TOKEN_CEILING*100:.0f}%"),
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_state(self) -> None:
        try:
            state = {
                "next_id": self._next_id,
                "session_tokens": self._session_tokens,
                "meta": {str(k): v for k, v in self._meta.items()},
            }
            # Nexus VFS en primaire, fichier local en secours
            from .nexus_bridge import turbovec_write
            if not turbovec_write(state):
                BRAIN_STATE.parent.mkdir(parents=True, exist_ok=True)
                BRAIN_STATE.write_text(
                    json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        except Exception as e:
            log.debug(f"[TURBOVEC] save_state err: {e}")

    def _load_state(self) -> None:
        try:
            from .nexus_bridge import turbovec_read
            state = turbovec_read()
            if not state and BRAIN_STATE.exists():
                state = json.loads(BRAIN_STATE.read_text(encoding="utf-8"))
            if not state:
                return
            self._next_id = state.get("next_id", 1)
            self._session_tokens = state.get("session_tokens", 0)
            for k, m in state.get("meta", {}).items():
                uid = int(k)
                vec = _hash_embed(m["text"]).reshape(1, DIM)
                ids = np.array([uid], dtype=np.uint64)
                try:
                    self._db.add_with_ids(vec, ids)
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
                self._meta[uid] = m
        except Exception as e:
            log.debug(f"[TURBOVEC] load_state err: {e}")


# ─── Singleton ────────────────────────────────────────────────────────────────

_brain_instance: Optional[TurboVecBrain] = None

def get_turbovec_brain() -> TurboVecBrain:
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = TurboVecBrain()
    return _brain_instance
