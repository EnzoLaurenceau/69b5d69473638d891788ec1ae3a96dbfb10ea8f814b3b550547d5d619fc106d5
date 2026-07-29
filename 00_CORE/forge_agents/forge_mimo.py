"""
forge_mimo.py — Xiaomi MiMo 2.5 pro provider + batch coalescer (round-up aware)
==============================================================================
MiMo facture les tokens ARRONDIS AU BLOC SUPÉRIEUR (1000 par défaut). Donc
10 appels de 200 tokens = 10 × 1000 facturés = 10 000, alors qu'un seul appel
groupé de 2000 tokens = 2000 facturés. Le batcher coalesce N petits prompts en
UN appel → on paie le round-up une fois au lieu de N.

Endpoints (réponse user) :
  OpenAI-compat : https://token-plan-ams.xiaomimimo.com/v1   (utilisé ici)
  Anthropic-compat : https://token-plan-ams.xiaomimimo.com/anthropic

Rôle : backend LLM INTERNE de la Forge (appelé par forge_call), Claude Code
reste l'orchestrateur. Activation : MIMO_API_KEY dans .env.

Config .env :
  MIMO_API_KEY=...            (obligatoire — sinon provider no-op)
  MIMO_BASE_URL=https://token-plan-ams.xiaomimimo.com/v1
  MIMO_MODEL=mimo-2.5-pro
  MIMO_TOKEN_BLOCK=1000       (taille du bloc de facturation round-up)

Dégradation gracieuse : pas de clé → is_available()=False, aucun appel.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ForgeMiMo")

FORGE_ROOT = Path(__file__).parent.parent.parent
DEFAULT_BASE = "https://token-plan-ams.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.5-pro"
DEFAULT_BLOCK = 1000


def _env(key: str, default: str = "") -> str:
    """Lit une variable d'environnement — supporte les alias XIAOMI_* pour MiMo."""
    # Alias : XIAOMI_API_KEY → MIMO_API_KEY, XIAOMI_OPENAI_ENDPOINT → MIMO_BASE_URL
    ALIASES = {
        "MIMO_API_KEY": "XIAOMI_API_KEY",
        "MIMO_BASE_URL": "XIAOMI_OPENAI_ENDPOINT",
        "MIMO_OPENAI_URL": "XIAOMI_OPENAI_ENDPOINT",
    }
    # Check env with aliases
    for try_key in [key, ALIASES.get(key, "")]:
        if try_key:
            v = os.environ.get(try_key)
            if v is not None:
                return v
    # Check .env files
    for p in [FORGE_ROOT / ".env", FORGE_ROOT / ".env.local"]:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, val = line.partition("=")
                    k = k.strip()
                    if k == key or k == ALIASES.get(key, ""):
                        return val.strip().strip('"').strip("'")
    return default


def token_block() -> int:
    try:
        return max(1, int(_env("MIMO_TOKEN_BLOCK", str(DEFAULT_BLOCK))))
    except ValueError:
        return DEFAULT_BLOCK


def round_up_tokens(n: int, block: Optional[int] = None) -> int:
    """Facturation réelle MiMo : arrondi au bloc supérieur."""
    b = block or token_block()
    return int(math.ceil(max(0, n) / b) * b)


def is_available() -> bool:
    return bool(_env("MIMO_API_KEY"))


def _base_url() -> str:
    # tolère MIMO_BASE_URL (ancien) ET MIMO_OPENAI_URL (renommage user)
    return _env("MIMO_OPENAI_URL", "") or _env("MIMO_BASE_URL", DEFAULT_BASE)


def _client():
    from openai import OpenAI
    return OpenAI(api_key=_env("MIMO_API_KEY"), base_url=_base_url(), max_retries=0)


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ─── Appel simple ─────────────────────────────────────────────────────────────

def mimo_call(prompt: str, system: str = "", max_tokens: int = 1000,
              timeout: int = 60) -> tuple[str, dict]:
    """Un appel MiMo. Retourne (texte, métriques round-up-aware)."""
    if not is_available():
        raise RuntimeError("MIMO_API_KEY absente")
    # mimo-2.5-pro is a REASONING model: reasoning_content is billed against the
    # completion budget BEFORE the answer. A small max_tokens starves `content`
    # to '' while still billing a full round-up block. Floor it so reasoning
    # never eats the whole answer. ponytail: floor 768; callers wanting long
    # outputs pass more, and round-up bills actual out tokens anyway.
    max_tokens = max(max_tokens, 768)
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    t0 = time.time()
    resp = _client().chat.completions.create(
        model=_env("MIMO_MODEL", DEFAULT_MODEL),
        messages=msgs, max_tokens=max_tokens, timeout=timeout)
    text = resp.choices[0].message.content or ""
    latency = int((time.time() - t0) * 1000)
    in_tok = getattr(resp.usage, "prompt_tokens", _est_tokens(prompt + system))
    out_tok = getattr(resp.usage, "completion_tokens", _est_tokens(text))
    billed = round_up_tokens(in_tok) + round_up_tokens(out_tok)
    _record_budget(billed, in_tok + out_tok)
    return text, {"in": in_tok, "out": out_tok, "billed_tokens": billed,
                  "latency_ms": latency, "calls": 1}


def _record_budget(billed: int, real: int) -> None:
    """Débite le plan mensuel MiMo. Point de passage UNIQUE : toutes les branches
    (batcher, swarm, judge) finissent ici, donc compter ici suffit.

    Import tardif (`mimo_budget` importe `_env` d'ici) et échec absorbé : un ledger
    illisible ne doit jamais faire échouer un appel LLM déjà payé.
    """
    try:
        from .mimo_budget import record
        record(billed, real_tokens=real)
    except Exception as exc:                      # noqa: BLE001
        logger.warning("budget MiMo non débité (%s) — le solde affiché sous-estime", exc)


# ─── Batch coalescer (le cœur de l'optimisation round-up) ────────────────────

_SPLIT_RE = re.compile(r"###(\d+)###")


class MimoBatcher:
    """
    Coalesce plusieurs prompts en UN appel MiMo → un seul round-up 1K au lieu
    de N. Les prompts sont numérotés, la réponse est re-splitée par marqueur.

    Usage :
        b = MimoBatcher()
        b.add("résume ceci: ...")
        b.add("classe ce texte: ...")
        results = b.flush()          # -> list[str] alignée sur l'ordre d'ajout

    Auto-flush : add() déclenche flush() quand l'estimation d'input dépasse
    max_block_tokens (défaut 1 bloc) — au-delà, grouper ne gagne plus rien.
    """

    def __init__(self, system: str = "", max_block_tokens: Optional[int] = None,
                 max_items: int = 20):
        self._prompts: list[str] = []
        self._system = system
        self._block = token_block()
        self._max_block_tokens = max_block_tokens or (self._block * 4)
        self._max_items = max_items
        self.stats = {"batches": 0, "items": 0, "billed_tokens": 0,
                      "naive_billed_tokens": 0}

    def _pending_tokens(self) -> int:
        return sum(_est_tokens(p) for p in self._prompts)

    def add(self, prompt: str) -> Optional[list[str]]:
        """Ajoute un prompt. Retourne des résultats si un auto-flush s'est produit."""
        self._prompts.append(prompt)
        if (len(self._prompts) >= self._max_items
                or self._pending_tokens() >= self._max_block_tokens):
            return self.flush()
        return None

    def flush(self, max_tokens_per_item: int = 400) -> list[str]:
        """Envoie tous les prompts en attente en UN appel, retourne la liste."""
        if not self._prompts:
            return []
        prompts, self._prompts = self._prompts, []

        if len(prompts) == 1:
            text, m = mimo_call(prompts[0], self._system, max_tokens=max_tokens_per_item)
            self._record(m, naive_items=1)
            return [text]

        packed = ("Réponds à CHAQUE requête numérotée séparément. Format STRICT : "
                  "commence chaque réponse par un marqueur ###N### (N = numéro), "
                  "puis la réponse. N'ajoute rien d'autre.\n\n")
        for i, p in enumerate(prompts, 1):
            packed += f"###{i}### {p}\n\n"

        # max_tokens aligné bloc : on paie le round-up de toute façon, autant l'utiliser
        budget = round_up_tokens(max_tokens_per_item * len(prompts))
        text, m = mimo_call(packed, self._system, max_tokens=budget)
        self._record(m, naive_items=len(prompts))
        return self._split(text, len(prompts))

    @staticmethod
    def _split(text: str, n: int) -> list[str]:
        """Re-split la réponse groupée par marqueur ###N###.
        ponytail: si le modèle ne respecte pas le format, fallback = tout dans [0]
        et le reste vide (plafond connu : dépend du respect du format par MiMo)."""
        parts = _SPLIT_RE.split(text)
        out = [""] * n
        # parts = [pre, "1", body1, "2", body2, ...]
        it = iter(parts[1:])
        found = False
        for num, body in zip(it, it):
            try:
                idx = int(num) - 1
                if 0 <= idx < n:
                    out[idx] = body.strip()
                    found = True
            except ValueError:
                continue
        if not found:
            out[0] = text.strip()
        return out

    def _record(self, m: dict, naive_items: int) -> None:
        self.stats["batches"] += 1
        self.stats["items"] += naive_items
        self.stats["billed_tokens"] += m["billed_tokens"]
        # Coût naïf : chaque item aurait payé son propre round-up (input+output)
        per_item_in = round_up_tokens(max(1, m["in"] // max(1, naive_items)))
        per_item_out = round_up_tokens(max(1, m["out"] // max(1, naive_items)))
        self.stats["naive_billed_tokens"] += naive_items * (per_item_in + per_item_out)

    def savings(self) -> dict:
        saved = self.stats["naive_billed_tokens"] - self.stats["billed_tokens"]
        return {**self.stats, "tokens_saved_vs_naive": max(0, saved)}


# ─── Self-check (sans réseau) ─────────────────────────────────────────────────

if __name__ == "__main__":
    assert round_up_tokens(1, 1000) == 1000
    assert round_up_tokens(1000, 1000) == 1000
    assert round_up_tokens(1001, 1000) == 2000
    assert round_up_tokens(0, 1000) == 0

    # split d'une réponse groupée bien formée
    packed_resp = "###1### résumé A\n\n###2### classe: positif\n\n###3### oui"
    parts = MimoBatcher._split(packed_resp, 3)
    assert parts == ["résumé A", "classe: positif", "oui"], parts

    # format cassé → fallback dans [0], pas de crash
    bad = MimoBatcher._split("réponse en vrac sans marqueur", 2)
    assert bad[0].startswith("réponse") and bad[1] == ""

    # batching offline : stub mimo_call pour compter les économies round-up
    calls = {"n": 0}

    def _stub(prompt, system="", max_tokens=1000, timeout=60):
        calls["n"] += 1
        n = prompt.count("###") // 2 or 1
        body = "".join(f"###{i}### r{i}\n" for i in range(1, n + 1)) if n > 1 else "r1"
        return body, {"in": 200 * n, "out": 50 * n,
                      "billed_tokens": round_up_tokens(200 * n) + round_up_tokens(50 * n),
                      "latency_ms": 10, "calls": 1}
    globals()["mimo_call"] = _stub   # MimoBatcher.flush lit le global du module

    b = MimoBatcher()
    for _ in range(5):
        b.add("petit prompt de test")   # 5 items, sous les seuils → pas d'auto-flush
    res = b.flush()
    assert calls["n"] == 1, f"attendu 1 appel groupé, eu {calls['n']}"
    assert len(res) == 5
    sv = b.savings()
    # 5 items groupés (1 round-up) < 5 items séparés (5 round-ups)
    assert sv["tokens_saved_vs_naive"] > 0, sv
    print("forge_mimo self-check: OK")
    print(f"  1 appel groupé pour 5 items | tokens économisés vs naïf: {sv['tokens_saved_vs_naive']}")
