"""mimo_budget.py — plafond d'abonnement MiMo (axe FOURNISSEUR, pas axe client).

POURQUOI CE FICHIER EXISTE
--------------------------
Depuis le 2026-07-25 il n'existe plus aucun tier LLM gratuit : Claude est couvert par
l'abonnement, tout le reste est facturé, et MiMo est la seule destination de volume
(17 €/mois pour 11 Md tokens). Or **personne ne comptait**. `mimo_token_tracker.py`
porte mal son nom — il compte des prospects, des octets et de la latence, et le dit
lui-même (« Pas de TokenUsage LLM »). Résultat : 4 Md tokens consommés sur 11 Md, suivis
nulle part, et un garde-fou (S-07) impossible à écrire faute de chiffre à comparer.

CE FICHIER N'EST PAS `forge_quota`
----------------------------------
Ce sont deux axes distincts qu'il ne faut pas confondre :

    forge_quota   → combien CE CLIENT a le droit de consommer, sur une fenêtre glissante
                    d'une heure. Compteur stocké DANS l'espace du tenant.
    mimo_budget   → combien il reste sur NOTRE abonnement fournisseur, sur le mois
                    calendaire. Compteur GLOBAL : le plan est partagé par tous les
                    tenants. Le cloisonner par tenant donnerait à chacun son propre
                    « 11 Md restants » — c'est-à-dire un chiffre faux, N fois.

D'où le régime `platform` dans `state_ownership.py`, aux côtés de `forge_quota` : le
fichier vit hors de l'espace des tenants, comme les limites elles-mêmes.

D'OÙ VIENT LE CHIFFRE (à lire avant de faire confiance à l'affichage)
---------------------------------------------------------------------
Le fournisseur n'expose pas — à ce jour — d'endpoint d'usage confirmé sur sa façade
OpenAI-compat. On ne devine pas d'URL. La consommation affichée est donc :

    consommation = point de départ déclaré  +  ce que ce dépôt a réellement facturé

Le point de départ (`MIMO_BASELINE_TOKENS`, 4 Md) est une **déclaration humaine** datée,
valable pour son seul mois (`MIMO_BASELINE_PERIOD`) ; le mois suivant repart du ledger
seul. Le ledger, lui, est mesuré : `mimo_call` y écrit le coût facturé de chaque appel.
`report()["source"]` dit lequel des deux domine, et `measured_since` dit depuis quand on
mesure vraiment — sans ça, on réafficherait un chiffre déclaré en le faisant passer pour
une mesure, ce qui est exactement ce que le sprint corrige.

Le jour où l'endpoint fournisseur est confirmé : poser `MIMO_USAGE_URL` (+ éventuellement
`MIMO_USAGE_FIELD`) et la source bascule sur `remote`. Rien d'autre ne bouge.

Config `.env` :
    MIMO_MONTHLY_TOKENS=11000000000   plan mensuel
    MIMO_BASELINE_TOKENS=4000000000   déjà consommé quand le compteur a été posé
    MIMO_BASELINE_PERIOD=2026-07      mois auquel ce point de départ s'applique
    MIMO_ALERT_PCT=80                 seuil d'alerte (S-07 s'en sert pour bloquer)
    MIMO_USAGE_URL=                   vide = pas d'appel réseau (défaut)
    MIMO_USAGE_FIELD=used_tokens      champ à lire dans la réponse, si URL posée

Self-check : python -m forge_agents.mimo_budget
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from .forge_mimo import _env

logger = logging.getLogger("MiMoBudget")

FORGE_ROOT = Path(__file__).resolve().parents[2]
#: Hors espace tenant — le plan fournisseur est commun (cf. `forge_quota.LIMITS_FILE`).
LEDGER_FILE = FORGE_ROOT / "05_STATE" / "identity" / "mimo_budget.json"

DEFAULT_PLAN = 11_000_000_000
DEFAULT_BASELINE = 4_000_000_000
DEFAULT_BASELINE_PERIOD = "2026-07"
DEFAULT_ALERT_PCT = 80

#: Le swarm appelle MiMo depuis un pool de 6 threads. Sans verrou, deux incréments
#: simultanés se écrasent et le compteur sous-estime — c'est-à-dire ment dans le sens
#: qui coûte cher. Le verrou couvre le processus ; deux processus concurrents peuvent
#: encore se marcher dessus (plafond connu, même trait que `forge_quota`).
_LOCK = threading.RLock()


class BudgetExceeded(RuntimeError):
    """Plan fournisseur épuisé. Même contrat que `forge_quota.QuotaExceeded` : on LÈVE.

    Tronquer en silence ferait exactement ce que ce module existe pour empêcher —
    continuer à dépenser sans que personne ne le voie.
    """

    def __init__(self, used: float, limit: float, period: str):
        self.provider, self.used, self.limit, self.period = "MiMo", used, limit, period
        super().__init__(
            f"budget MiMo épuisé sur {period} : {used:,.0f} / {limit:,.0f} tokens facturés"
        )


# ── Configuration ─────────────────────────────────────────────────────────────

def _int_env(key: str, default: int) -> int:
    try:
        return int(str(_env(key, str(default))).strip() or default)
    except (ValueError, TypeError):
        # Config illisible : on N'OUVRE PAS les vannes, on applique le défaut.
        logger.warning("%s illisible — valeur par défaut (%s)", key, default)
        return default


def plan_tokens() -> int:
    return max(0, _int_env("MIMO_MONTHLY_TOKENS", DEFAULT_PLAN))


def alert_pct() -> int:
    return min(100, max(0, _int_env("MIMO_ALERT_PCT", DEFAULT_ALERT_PCT)))


def current_period() -> str:
    """Mois calendaire UTC — le plan MiMo est mensuel, pas glissant."""
    return time.strftime("%Y-%m", time.gmtime())


def baseline_for(period: str) -> int:
    """Point de départ déclaré. Ne s'applique QU'À son mois : sinon on le re-compterait
    tous les mois et le solde ne remonterait jamais."""
    declared = _env("MIMO_BASELINE_PERIOD", DEFAULT_BASELINE_PERIOD).strip()
    if period != declared:
        return 0
    return max(0, _int_env("MIMO_BASELINE_TOKENS", DEFAULT_BASELINE))


# ── Ledger ────────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        data = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        # Ledger corrompu : on repart à zéro EN LE DISANT. Un compteur muet qui
        # redémarre à 0 est pire qu'un compteur absent.
        logger.error("ledger MiMo illisible (%s) — repart de zéro pour ce mois", exc)
        return {}


def _save(data: dict) -> None:
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, LEDGER_FILE)


def _entry(data: dict, period: str) -> dict:
    e = data.setdefault("periods", {}).setdefault(period, {})
    e.setdefault("billed_tokens", 0)
    e.setdefault("real_tokens", 0)
    e.setdefault("calls", 0)
    return e


def record(billed_tokens: int, real_tokens: int = 0, calls: int = 1) -> dict:
    """Enregistre le coût d'un appel MiMo. Appelé par `mimo_call`, jamais bloquant.

    `real_tokens` (in+out non arrondis) est gardé à côté du facturé : c'est l'écart
    entre les deux qui chiffre le round-up (S-05), sans avoir à réinstrumenter plus tard.
    """
    period = current_period()
    with _LOCK:
        data = _load()
        e = _entry(data, period)
        e["billed_tokens"] += max(0, int(billed_tokens))
        e["real_tokens"] += max(0, int(real_tokens))
        e["calls"] += max(0, int(calls))
        now = time.time()
        e.setdefault("first_ts", now)
        e["last_ts"] = now
        _save(data)
        return dict(e)


def ledger(period: Optional[str] = None) -> dict:
    """Ce que CE dépôt a mesuré sur le mois (hors point de départ déclaré)."""
    p = period or current_period()
    e = _load().get("periods", {}).get(p, {})
    return {"billed_tokens": int(e.get("billed_tokens", 0)),
            "real_tokens": int(e.get("real_tokens", 0)),
            "calls": int(e.get("calls", 0)),
            "first_ts": e.get("first_ts"), "last_ts": e.get("last_ts")}


# ── Lecture fournisseur (désactivée tant que l'endpoint n'est pas confirmé) ───

_remote_cache: dict = {"ts": 0.0, "value": None}
_REMOTE_TTL = 60.0


def remote_usage() -> Optional[int]:
    """Consommation lue chez MiMo. Rend `None` tant que `MIMO_USAGE_URL` n'est pas posée.

    On ne devine pas d'URL : un endpoint inventé rendrait 0 ou une erreur, et un 0
    afficherait « 11 Md restants » — le genre de chiffre faux que ce sprint supprime.
    Résultat mis en cache 60 s : la console interroge le budget toutes les 4 s.
    """
    url = _env("MIMO_USAGE_URL", "").strip()
    if not url:
        return None
    now = time.time()
    if now - _remote_cache["ts"] < _REMOTE_TTL:
        return _remote_cache["value"]
    value = None
    try:
        import urllib.request
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {_env('MIMO_API_KEY')}"})
        with urllib.request.urlopen(req, timeout=5) as resp:      # nosec B310 - URL opérateur
            payload = json.loads(resp.read().decode("utf-8"))
        field = _env("MIMO_USAGE_FIELD", "used_tokens").strip()
        raw = payload.get(field) if isinstance(payload, dict) else None
        value = int(raw) if raw is not None else None
    except Exception as exc:                                       # noqa: BLE001
        # Le fournisseur injoignable ne doit jamais casser un tableau de bord : on
        # retombe sur le ledger local, et `source` le dira.
        logger.warning("lecture usage MiMo impossible (%s) — repli sur le ledger local", exc)
        value = None
    _remote_cache.update({"ts": now, "value": value})
    return value


# ── Consommation et garde-fou ────────────────────────────────────────────────

def used(period: Optional[str] = None) -> int:
    """Tokens facturés consommés sur le mois : fournisseur si disponible, sinon
    point de départ déclaré + ledger mesuré."""
    p = period or current_period()
    remote = remote_usage() if p == current_period() else None
    if remote is not None:
        return max(0, remote)
    return baseline_for(p) + ledger(p)["billed_tokens"]


def remaining(period: Optional[str] = None) -> int:
    return max(0, plan_tokens() - used(period))


def check(cost_tokens: int = 0, enforce: bool = True) -> int:
    """Le budget supporte-t-il `cost_tokens` de plus ? Lève `BudgetExceeded` sinon.

    Vérifie AVANT de dépenser (contrairement à `forge_quota.consume`, qui compte puis
    refuse) : ici l'appel n'est pas encore parti, on peut encore ne pas le payer.
    `enforce=False` = mode observation, retourne sans lever.
    """
    period = current_period()
    total = used(period) + max(0, int(cost_tokens))
    limit = plan_tokens()
    if enforce and limit and total > limit:
        raise BudgetExceeded(total, limit, period)
    return total


def report() -> dict:
    """État du budget fournisseur — consommé par `/v1/budget/mimo` et la console."""
    period = current_period()
    led = ledger(period)
    base = baseline_for(period)
    remote = remote_usage()
    total = used(period)
    limit = plan_tokens()
    pct = round(100 * total / limit, 2) if limit else 0.0
    return {
        "provider": "MiMo",
        "period": period,
        "plan_tokens": limit,
        "used_tokens": total,
        "remaining_tokens": max(0, limit - total),
        "pct": pct,
        "alert_pct": alert_pct(),
        "over_alert": pct >= alert_pct(),
        # `source` est la partie la plus importante du rapport : elle dit si le chiffre
        # affiché est mesuré ou déclaré. Sans elle, la console referait la promesse que
        # S-02 vient de retirer au routeur.
        "source": "remote" if remote is not None else ("local" if led["calls"] else "declared"),
        "baseline_tokens": base,
        "ledger_billed_tokens": led["billed_tokens"],
        "ledger_real_tokens": led["real_tokens"],
        "calls": led["calls"],
        "measured_since": led["first_ts"],
        "configured": bool(_env("MIMO_API_KEY", "").strip()),
    }


# ── Self-check (sans réseau, sans toucher au ledger réel) ────────────────────

if __name__ == "__main__":  # pragma: no cover
    import tempfile

    failures = []

    def check_(cond, label):
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        if not cond:
            failures.append(label)

    tmpdir = tempfile.mkdtemp(prefix="mimo-budget-")
    LEDGER_FILE = Path(tmpdir) / "mimo_budget.json"   # ledger jetable : on ne touche pas au réel
    os.environ["MIMO_MONTHLY_TOKENS"] = "10000"
    os.environ["MIMO_BASELINE_TOKENS"] = "1000"
    os.environ["MIMO_BASELINE_PERIOD"] = current_period()
    os.environ["MIMO_USAGE_URL"] = ""
    os.environ.pop("MIMO_ALERT_PCT", None)

    print("[1] Point de départ déclaré")
    check_(used() == 1000, f"baseline appliquée à son mois (used={used()})")
    check_(baseline_for("1999-01") == 0, "baseline ignorée sur un autre mois")

    print("\n[2] Le ledger mesure")
    record(2000, real_tokens=1200)
    record(3000, real_tokens=1500)
    check_(ledger()["calls"] == 2, "2 appels comptés")
    check_(used() == 6000, f"baseline + facturé (used={used()})")
    check_(ledger()["real_tokens"] == 2700, "réel gardé à côté du facturé (round-up S-05)")

    print("\n[3] Le dépassement LÈVE")
    check_(check(1000) == 7000, "sous le plan : passe et retourne le total projeté")
    try:
        check(5000)
        check_(False, "au-dessus du plan : lève")
    except BudgetExceeded as exc:
        check_(exc.used == 11000 and exc.limit == 10000, f"refus explicite ({exc})")
    check_(check(5000, enforce=False) == 11000, "enforce=False observe sans lever")

    print("\n[4] Rapport")
    r = report()
    check_(r["source"] == "local", f"source mesurée annoncée (source={r['source']})")
    check_(r["remaining_tokens"] == 4000, f"solde restant ({r['remaining_tokens']})")
    check_(r["over_alert"] is False, f"60 % < seuil {r['alert_pct']} %")

    print("\n[5] Ledger corrompu → repart de zéro, pas de crash")
    LEDGER_FILE.write_text("{ pas du json", encoding="utf-8")
    check_(ledger()["billed_tokens"] == 0 and used() == 1000,
           "corruption absorbée, baseline conservée")

    print("\n" + ("ALL TESTS PASSED" if not failures else f"{len(failures)} FAILURE(S): {failures}"))
    raise SystemExit(1 if failures else 0)
