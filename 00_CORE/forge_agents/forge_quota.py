"""forge_quota.py — limites par tenant : stockage, débit, tokens LLM.

POURQUOI
--------
En multi-tenant, un client qui déborde ne doit pas dégrader les autres. Sans quota, la
première boucle mal écrite d'un tenant remplit le disque ou épuise le budget LLM commun.

CE QUI EST COMPTÉ
-----------------
- `storage_bytes` : empreinte disque du tenant (mesurée par `forge_store.stats()`)
- `requests`      : nombre de requêtes sur une fenêtre glissante
- `llm_tokens`    : tokens consommés sur une fenêtre glissante

CHOIX DE CONCEPTION
-------------------
- **Fenêtre glissante par seaux** (buckets d'une minute) plutôt qu'un compteur remis à zéro :
  un compteur remis à zéro autorise le double du quota à cheval sur la bascule.
- **Le dépassement LÈVE** (`QuotaExceeded`) plutôt que de tronquer en silence. Une écriture
  silencieusement perdue est bien pire qu'une erreur visible.
- **Compteurs stockés dans l'espace du tenant** : pas de registre central à verrouiller,
  et un tenant ne peut pas lire la consommation d'un autre.
- Les limites, elles, vivent HORS de l'espace du tenant — sinon un client pourrait
  réécrire son propre quota.

Self-check : python -m forge_agents.forge_quota
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from .forge_tenant import current_tenant, validate

logger = logging.getLogger("ForgeQuota")

FORGE_ROOT = Path(__file__).resolve().parents[2]
LIMITS_FILE = FORGE_ROOT / "05_STATE" / "identity" / "quotas.json"

WINDOW_SECONDS = 3600          # fenêtre glissante d'une heure
BUCKET_SECONDS = 60            # granularité : la minute


class QuotaExceeded(RuntimeError):
    """Limite atteinte. Porte la ressource, l'usage et la limite pour un message utile."""

    def __init__(self, resource: str, used: float, limit: float, tenant: str):
        self.resource, self.used, self.limit, self.tenant = resource, used, limit, tenant
        super().__init__(
            f"quota dépassé pour {tenant!r} sur {resource} : {used:,.0f} / {limit:,.0f}"
        )


@dataclass
class Limits:
    storage_bytes: int = 512 * 1024 * 1024      # 512 Mo
    requests: int = 10_000                      # par fenêtre
    llm_tokens: int = 2_000_000                 # par fenêtre

    @staticmethod
    def unlimited() -> "Limits":
        big = 10 ** 15
        return Limits(storage_bytes=big, requests=big, llm_tokens=big)


def _load_limits() -> dict:
    try:
        return json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        # Limites illisibles : on N'OUVRE PAS les vannes. On applique le défaut.
        logger.error("quotas illisibles (%s) — application des limites par défaut", exc)
        return {}


def limits_for(tenant: str | None = None) -> Limits:
    """Limites du tenant : override explicite, sinon `default`, sinon les valeurs du code."""
    tid = validate(tenant) if tenant else current_tenant()
    data = _load_limits()
    raw = data.get(tid) or data.get("default") or {}
    base = asdict(Limits())
    base.update({k: v for k, v in raw.items() if k in base})
    return Limits(**base)


def set_limits(tenant: str, **kwargs) -> Limits:
    """Fixe les limites d'un tenant. Écrit HORS de l'espace du tenant (non falsifiable)."""
    tid = validate(tenant)
    data = _load_limits()
    entry = data.get(tid, {})
    for k, v in kwargs.items():
        if k not in asdict(Limits()):
            raise ValueError(f"ressource inconnue: {k}")
        entry[k] = int(v)
    data[tid] = entry
    LIMITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIMITS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, LIMITS_FILE)
    return limits_for(tid)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPTEURS — fenêtre glissante par seaux d'une minute
# ═══════════════════════════════════════════════════════════════════════════════

#: namespace des compteurs dans l'espace du tenant. Pas de préfixe `_` : `forge_store`
#: exige un premier caractère alphanumérique (validation qui a servi dès le premier essai).
_NS = "quota"


def _now_bucket() -> int:
    return int(time.time() // BUCKET_SECONDS)


def _read_buckets(resource: str) -> dict:
    from . import forge_store
    return forge_store.get(_NS, f"{resource}.json", default={}) or {}


def _write_buckets(resource: str, buckets: dict) -> None:
    from . import forge_store
    forge_store.put(_NS, f"{resource}.json", buckets)


def usage(resource: str) -> float:
    """Consommation du tenant courant sur la fenêtre glissante."""
    cutoff = _now_bucket() - (WINDOW_SECONDS // BUCKET_SECONDS)
    return float(sum(v for b, v in _read_buckets(resource).items() if int(b) > cutoff))


def consume(resource: str, amount: float = 1.0, enforce: bool = True) -> float:
    """Ajoute `amount` à la consommation. Lève `QuotaExceeded` si la limite est franchie.

    La vérification a lieu APRÈS incrément : on refuse la requête qui fait dépasser, pas
    la suivante. `enforce=False` compte sans bloquer (mode observation).
    """
    tid = current_tenant()
    buckets = _read_buckets(resource)
    cutoff = _now_bucket() - (WINDOW_SECONDS // BUCKET_SECONDS)
    buckets = {b: v for b, v in buckets.items() if int(b) > cutoff}   # purge des vieux seaux
    key = str(_now_bucket())
    buckets[key] = buckets.get(key, 0) + amount
    _write_buckets(resource, buckets)

    total = float(sum(buckets.values()))
    limit = float(getattr(limits_for(tid), resource, 0) or 0)
    if enforce and limit and total > limit:
        raise QuotaExceeded(resource, total, limit, tid)
    return total


def check_storage(enforce: bool = True) -> dict:
    """Vérifie l'empreinte disque du tenant courant."""
    from . import forge_store
    tid = current_tenant()
    used = forge_store.stats()["bytes"]
    limit = limits_for(tid).storage_bytes
    if enforce and used > limit:
        raise QuotaExceeded("storage_bytes", used, limit, tid)
    return {"tenant": tid, "used": used, "limit": limit,
            "pct": round(100 * used / limit, 1) if limit else 0.0}


def report() -> dict:
    """État des quotas du tenant courant — pour la page santé et l'API."""
    tid = current_tenant()
    lim = limits_for(tid)
    from . import forge_store
    return {
        "tenant": tid,
        "limits": asdict(lim),
        "usage": {
            "storage_bytes": forge_store.stats()["bytes"],
            "requests": usage("requests"),
            "llm_tokens": usage("llm_tokens"),
        },
        "window_seconds": WINDOW_SECONDS,
    }


if __name__ == "__main__":  # pragma: no cover
    import shutil
    from .forge_tenant import tenant_scope
    from . import forge_store

    failures = []

    def check(cond, label):
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        if not cond:
            failures.append(label)

    T = "quota-test"
    shutil.rmtree(forge_store.TENANTS_ROOT / T, ignore_errors=True)
    backup = LIMITS_FILE.read_text(encoding="utf-8") if LIMITS_FILE.exists() else None
    try:
        print("[1] Limites")
        set_limits(T, requests=5, llm_tokens=1000, storage_bytes=10_000)
        with tenant_scope(T):
            lim = limits_for()
            check(lim.requests == 5 and lim.llm_tokens == 1000, "limites appliquées au tenant")

        print("\n[2] Comptage et refus")
        with tenant_scope(T):
            for i in range(5):
                consume("requests")
            check(usage("requests") == 5, "5 requêtes comptées")
            try:
                consume("requests")
                check(False, "la 6e requête est refusée")
            except QuotaExceeded as exc:
                check(exc.resource == "requests" and exc.used == 6, f"refus explicite ({exc})")

        print("\n[3] Mode observation")
        with tenant_scope(T):
            before = usage("llm_tokens")
            consume("llm_tokens", 5000, enforce=False)
            check(usage("llm_tokens") == before + 5000, "compte sans bloquer si enforce=False")

        print("\n[4] Isolation des compteurs")
        other = "quota-other"
        shutil.rmtree(forge_store.TENANTS_ROOT / other, ignore_errors=True)
        with tenant_scope(other):
            check(usage("requests") == 0, "un tenant ne voit pas la consommation d'un autre")

        print("\n[5] Stockage")
        with tenant_scope(T):
            forge_store.put("gros", "data.json", {"x": "y" * 20_000})
            try:
                check_storage()
                check(False, "dépassement de stockage détecté")
            except QuotaExceeded as exc:
                check(exc.resource == "storage_bytes", f"refus stockage ({exc.used:,} > {exc.limit:,})")
            r = check_storage(enforce=False)
            check(r["pct"] > 100, f"rapport sans blocage: {r['pct']}%")

        print("\n[6] Limites illisibles → défaut, pas de vannes ouvertes")
        LIMITS_FILE.write_text("{ pas du json", encoding="utf-8")
        with tenant_scope(T):
            check(limits_for().requests == Limits().requests,
                  "registre corrompu → limites par défaut (jamais illimité)")
    finally:
        if backup is not None:
            LIMITS_FILE.write_text(backup, encoding="utf-8")
        else:
            LIMITS_FILE.unlink(missing_ok=True)
        for t in (T, "quota-other"):
            shutil.rmtree(forge_store.TENANTS_ROOT / t, ignore_errors=True)

    print("\n" + ("ALL TESTS PASSED" if not failures else f"{len(failures)} FAILURE(S): {failures}"))
    raise SystemExit(1 if failures else 0)
