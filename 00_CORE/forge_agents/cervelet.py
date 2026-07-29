"""
cervelet.py — Cervelet Artificiel + Système d'Âme Homéostatique + Layer Mémoire
================================================================================
Implémentation de optiforge.txt §1-3.

Architecture :
  SystèmeHoméostatique  → état interne (budget, humeur, anxiété)
  LayerMémoirePostgresRedis → RAM (dict) + persistence JSON (fallback PostgreSQL/Redis)
  CerveletArtificiel    → intercepte les Token-IDs AVANT appel LLM

Intégration Forge :
  cervelet_intercept(token_id) → appelé depuis forge_llm._call_anthropic()
  Si réflexe ancré → résultat direct, 0 token LLM consommé
  Si inconnu → None (laisse passer au Cortex/LLM)

Token-ID Protocol :
  Format : "<target>#<action_id>:<arg1>,<arg2>"
  Ex     : "200#10:3500,1200"  (target 200, action SUBTRACT, 3500-1200)
  Codes actions :
    10 → SUBTRACT (v1 - v2)
    11 → ADD      (v1 + v2)
    12 → RATIO    (v1 / v2, 4 décimales)
    13 → CLAMP    (v1 min=0 max=v2)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent
CERVELET_STATE_FILE = FORGE_ROOT / ".nexus" / "cervelet_state.json"
CERVELET_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

# Seuil avant qu'une routine devienne un réflexe ancré en RAM
SEUIL_REFLEXE = 3

# Poids synaptiques (optiforge §3, Règle 2) : un réflexe fautif voit son poids
# baisser ; sous le seuil il est détruit et le Cortex reprend le contrôle.
POIDS_INITIAL = 1.0
POIDS_PENALITE_ERREUR = 0.5
POIDS_SEUIL_DESTRUCTION = 0.3

# Codes d'action Token-ID
_ACTION_MAP: dict[str, Callable[[int, int], Any]] = {
    "10": lambda v1, v2: v1 - v2,           # SUBTRACT
    "11": lambda v1, v2: v1 + v2,           # ADD
    "12": lambda v1, v2: round(v1 / v2, 4) if v2 else 0,  # RATIO
    "13": lambda v1, v2: max(0, min(v1, v2)),  # CLAMP
}


# ─── Système d'Âme Homéostatique ─────────────────────────────────────────────

class SystèmeHoméostatique:
    """Gère l'état interne de la Forge : budget, humeur, instinct de survie."""

    def __init__(self, budget_initial: float = 100.0):
        self.budget_restant: float = budget_initial
        self.ratio_succès: float = 1.0
        self._total_appels: int = 0
        self._succès: int = 0

    def obtenir_état_âme(self) -> dict:
        anxiété = "Élevée" if self.budget_restant < 20.0 else "Basse"
        humeur = "Créative" if self.ratio_succès > 0.8 else "Dépressive/Prudente"
        return {
            "anxiété": anxiété,
            "humeur": humeur,
            "survie_critique": self.budget_restant < 5.0,
            "budget_restant": round(self.budget_restant, 4),
            "ratio_succès": round(self.ratio_succès, 3),
        }

    def impacter_budget(self, coût: float) -> None:
        self.budget_restant = max(0.0, self.budget_restant - coût)

    def intégrer_reward(self, reward_delta: float) -> None:
        """Intègre les récompenses/pénalités RLHF dans l'état émotionnel et la viabilité."""
        if reward_delta > 0:
            # Recompense : booste l'humeur et soulage l'anxiété
            self.ratio_succès = min(1.0, self.ratio_succès + reward_delta * 0.05)
        else:
            # Pénalité : dégrade le ratio de succès
            self.ratio_succès = max(0.0, self.ratio_succès + reward_delta * 0.1)

    def enregistrer_résultat(self, succès: bool) -> None:
        self._total_appels += 1
        if succès:
            self._succès += 1
        self.ratio_succès = self._succès / self._total_appels if self._total_appels else 1.0

    def to_dict(self) -> dict:
        return {
            "budget_restant": self.budget_restant,
            "ratio_succès": self.ratio_succès,
            "_total_appels": self._total_appels,
            "_succès": self._succès,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SystèmeHoméostatique":
        obj = cls(budget_initial=d.get("budget_restant", 100.0))
        obj.ratio_succès = d.get("ratio_succès", 1.0)
        obj._total_appels = d.get("_total_appels", 0)
        obj._succès = d.get("_succès", 0)
        return obj


# ─── Layer Mémoire PostgreSQL/Redis (minimaliste) ────────────────────────────

class LayerMémoirePostgresRedis:
    """
    Stack mémoire à deux vitesses, branchée sur forge_db (optiforge) :
      flash_mem_redis  → cache RAM process-local des lambdas (lecture < 1µs)
      compteurs/poids  → Redis via forge_db.hot_* (clés `cervelet:*`)
      profonde_postgres → table PG `episodes` via forge_db.deep_insert

    forge_db gère lui-même la bascule sur le secours (SQLite/graph.json) si
    PG/Redis sont down — cette couche n'a donc plus de fallback JSON propre.
    Les dicts locaux (`_compteur_routines`, `flash_mem_redis`) restent comme
    cache chaud du processus ; la source de vérité est forge_db.
    """

    def __init__(self, state_file: Path = CERVELET_STATE_FILE):
        self.state_file = state_file
        self.flash_mem_redis: dict[str, Callable[[], Any]] = {}  # Token-ID → lambda (cache RAM)
        self.profonde_postgres: list[dict] = []                  # buffer logs récents (cache)
        self._compteur_routines: dict[str, int] = {}             # cache compteurs
        self._poids: dict[str, float] = {}                       # cache poids synaptiques
        self._db = None
        try:
            from .forge_db import get_db
            self._db = get_db()
        except Exception as e:
            logger.warning(f"[Cervelet] forge_db indisponible : {e}")

    # ── Helpers forge_db ──────────────────────────────────────────────────────

    def _ck(self, kind: str, token_id: str) -> str:
        return f"cervelet:{kind}:{token_id}"

    # ── API publique ─────────────────────────────────────────────────────────

    def persister_log(self, token_id: str, resultat: Any, etat_ame: dict) -> None:
        rec = {"signal": token_id, "res": str(resultat), "meta": etat_ame,
               "salience": 0.0, "ts": time.time()}
        self.profonde_postgres.append(rec)
        self.profonde_postgres = self.profonde_postgres[-500:]
        if self._db:
            try:
                self._db.deep_insert("episodes", rec)
            except Exception as e:
                logger.debug(f"[Cervelet] persister_log forge_db: {e}")

    def incrémenter_routine(self, token_id: str) -> int:
        if self._db:
            try:
                n = self._db.hot_incr(self._ck("count", token_id))
                self._compteur_routines[token_id] = n
                return n
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        self._compteur_routines[token_id] = self._compteur_routines.get(token_id, 0) + 1
        return self._compteur_routines[token_id]

    def ancrer_reflexe(self, token_id: str, fn: Callable[[], Any]) -> None:
        self.flash_mem_redis[token_id] = fn
        self._poids[token_id] = POIDS_INITIAL
        if self._db:
            try:
                self._db.hot_set(self._ck("poids", token_id), str(POIDS_INITIAL))
                self._db.hot_set(self._ck("reflexe", token_id), "1")
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        logger.info(f"[CERVELET] Arc réflexe ancré (poids={POIDS_INITIAL}) : {token_id}")

    def poids(self, token_id: str) -> float:
        if token_id in self._poids:
            return self._poids[token_id]
        if self._db:
            try:
                v = self._db.hot_get(self._ck("poids", token_id))
                if v is not None:
                    self._poids[token_id] = float(v)
                    return self._poids[token_id]
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return POIDS_INITIAL

    def affaiblir_reflexe(self, token_id: str, penalite: float = POIDS_PENALITE_ERREUR) -> float:
        """Règle 2 : baisse le poids synaptique sur erreur ; détruit sous le seuil."""
        nouveau = self.poids(token_id) - penalite
        self._poids[token_id] = nouveau
        if self._db:
            try:
                self._db.hot_set(self._ck("poids", token_id), str(nouveau))
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        if nouveau < POIDS_SEUIL_DESTRUCTION:
            self.détruire_reflexe(token_id)
        return nouveau

    def détruire_reflexe(self, token_id: str) -> None:
        """Règle 2 : réflexe fautif détruit, le Cortex reprend le contrôle."""
        self.flash_mem_redis.pop(token_id, None)
        self._compteur_routines[token_id] = 0
        self._poids.pop(token_id, None)
        if self._db:
            try:
                self._db.hot_set(self._ck("count", token_id), "0")
                self._db.hot_set(self._ck("reflexe", token_id), "0")
                self._db.hot_set(self._ck("poids", token_id), "0")
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        logger.warning(f"[CERVELET] Arc réflexe détruit (poids < seuil) : {token_id}")

    def _reancrer_reflexe(self, token_id: str) -> None:
        fn = _parse_token_action(token_id)
        if fn:
            self.flash_mem_redis[token_id] = fn

    def rehydrater_reflexe(self, token_id: str) -> bool:
        """
        Réhydrate le lambda d'un réflexe depuis le store si absent du cache RAM
        (les lambdas ne persistent pas entre processus — seuls compteurs/poids/flag
        sont dans Redis/secours). Reconstruit si le flag réflexe est armé et le
        poids synaptique est au-dessus du seuil de destruction.
        """
        if token_id in self.flash_mem_redis:
            return True
        if not self._db:
            return False
        try:
            armed = self._db.hot_get(self._ck("reflexe", token_id)) == "1"
            if armed and self.poids(token_id) >= POIDS_SEUIL_DESTRUCTION:
                self._reancrer_reflexe(token_id)
                return token_id in self.flash_mem_redis
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return False


# ─── Parsing Token-ID ─────────────────────────────────────────────────────────

def _parse_token_action(token_id: str) -> Optional[Callable[[], Any]]:
    """Décode un Token-ID et retourne la lambda correspondante, ou None si invalide."""
    try:
        _target, payload = token_id.split("#", 1)
        action_id, args = payload.split(":", 1)
        parts = args.split(",")
        v1, v2 = int(parts[0]), int(parts[1])
        fn_base = _ACTION_MAP.get(action_id)
        if fn_base is None:
            return None
        return lambda v1=v1, v2=v2, fn=fn_base: fn(v1, v2)
    except Exception:
        return None


# ─── Cervelet Artificiel ──────────────────────────────────────────────────────

class CerveletArtificiel:
    """
    Intercepte les Token-IDs AVANT tout appel LLM.
    Cycle :
      1. Mode survie → ERR:SURVIE si budget critique
      2. Réflexe RAM → résultat immédiat (< 1µs, coût 0.0001€)
      3. Apprentissage → incrémente compteur, ancre si seuil atteint
      4. None → transmis au Cortex (LLM)

    Règle de destruction (Règle 2 optiforge §3) :
      Si un appel retourne un statut d'erreur 40x, appeler `signaler_erreur_reflexe()`.
    """

    def __init__(
        self,
        memoire: Optional[LayerMémoirePostgresRedis] = None,
        ame: Optional[SystèmeHoméostatique] = None,
    ):
        self.memoire = memoire or LayerMémoirePostgresRedis()
        self.ame = ame or _charger_ame()

    # ── Interception principale ───────────────────────────────────────────────

    def intercepter(self, token_id: str) -> Optional[str]:
        """
        Retourne une chaîne résultat si le cervelet peut répondre seul.
        Retourne None si le Cortex (LLM) doit prendre en charge.
        """
        état = self.ame.obtenir_état_âme()

        if état["survie_critique"]:
            logger.critical("[CERVELET] BUDGET CRITIQUE — arrêt d'urgence")
            return "ERR:SURVIE_BUDGET_STOP"

        # Réhydrate le réflexe depuis le store si absent du cache RAM (process froid)
        self.memoire.rehydrater_reflexe(token_id)

        # Réflexe RAM ?
        if token_id in self.memoire.flash_mem_redis:
            try:
                val = self.memoire.flash_mem_redis[token_id]()
                self.ame.impacter_budget(0.0001)
                self.ame.enregistrer_résultat(True)
                result_str = f"200:20:{val} (Réflexe Cervelet)"
                self.memoire.persister_log(token_id, result_str, état)
                return result_str
            except Exception as e:
                logger.error(f"[CERVELET] Erreur réflexe {token_id} : {e}")
                self.signaler_erreur_reflexe(token_id)
                # Retombe sur le Cortex
                return None

        # Apprentissage
        count = self.memoire.incrémenter_routine(token_id)
        if count >= SEUIL_REFLEXE:
            fn = _parse_token_action(token_id)
            if fn:
                self.memoire.ancrer_reflexe(token_id, fn)

        return None  # Cortex prend en charge

    def signaler_erreur_reflexe(self, token_id: str) -> None:
        """Règle 2 : un réflexe fautif voit son poids baisser ; détruit sous le seuil."""
        poids = self.memoire.affaiblir_reflexe(token_id)
        self.ame.enregistrer_résultat(False)
        logger.info(f"[CERVELET] Réflexe {token_id} affaibli → poids={poids:.2f}")

    def renforcer_reflexe(self, token_id: str, bonus: float = 0.2) -> None:
        """Renforce un réflexe ayant obtenu une récompense positive."""
        poids_actuel = self.memoire.poids(token_id)
        nouveau_poids = min(2.0, poids_actuel + bonus)
        self.memoire._poids[token_id] = nouveau_poids
        if self.memoire._db:
            try:
                self.memoire._db.hot_set(self.memoire._ck("poids", token_id), str(nouveau_poids))
            except Exception:
                pass
        self.ame.enregistrer_résultat(True)
        logger.info(f"[CERVELET] Réflexe {token_id} renforcé → poids={nouveau_poids:.2f}")

    def état(self) -> dict:
        return {
            "âme": self.ame.obtenir_état_âme(),
            "réflexes_en_ram": list(self.memoire.flash_mem_redis.keys()),
            "compteurs": dict(self.memoire._compteur_routines),
        }


# ─── Singleton Forge ──────────────────────────────────────────────────────────

_cervelet_instance: Optional[CerveletArtificiel] = None
_ame_instance: Optional[SystèmeHoméostatique] = None


def _charger_ame() -> SystèmeHoméostatique:
    global _ame_instance
    if _ame_instance:
        return _ame_instance
    if CERVELET_STATE_FILE.exists():
        try:
            data = json.loads(CERVELET_STATE_FILE.read_text(encoding="utf-8"))
            if "ame" in data:
                _ame_instance = SystèmeHoméostatique.from_dict(data["ame"])
                return _ame_instance
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    _ame_instance = SystèmeHoméostatique()
    return _ame_instance


def get_cervelet() -> CerveletArtificiel:
    """Singleton thread-safe (suffisant pour usage mono-thread Forge)."""
    global _cervelet_instance
    if _cervelet_instance is None:
        _cervelet_instance = CerveletArtificiel()
    return _cervelet_instance


def cervelet_intercept(token_id: str) -> Optional[str]:
    """
    Point d'entrée unique pour forge_llm.py.
    Appeler AVANT tout appel API LLM.

    Returns:
        str  → résultat disponible, pas besoin d'appeler le LLM
        None → le LLM doit être appelé normalement
    """
    return get_cervelet().intercepter(token_id)


# Sentinelle : la requête doit monter au Cortex (LangGraph / LLM)
ESCALATE = "ESCALATE"


def route_request(signal: str) -> str:
    """
    Routage NIVEAU REQUÊTE (optiforge two-tier) — appelé AVANT d'instancier
    LangGraph. Si un réflexe Token-ID résout en RAM/Redis, on évite totalement
    de démarrer le graphe (LangGraph = ralentissement pour le routinier).

    Returns:
        Le résultat réflexe (str) si le Cervelet sait répondre,
        sinon la sentinelle ESCALATE → l'appelant lance le Cortex (LangGraph).
    """
    looks_token = "#" in signal and ":" in signal
    if not looks_token:
        return ESCALATE  # tâche en langage naturel → Cortex direct
    result = get_cervelet().intercepter(signal)
    if result is None or result == "ERR:SURVIE_BUDGET_STOP":
        return result if result else ESCALATE
    return result


# ─── CLI de test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=== SIMULATION CERVELET ARTIFICIEL ===\n")
    cervelet = get_cervelet()
    commande = sys.argv[1] if len(sys.argv) > 1 else "200#10:3500,1200"

    for cycle in range(1, 6):
        print(f"[Cycle {cycle}] signal : '{commande}'")
        resultat = cervelet.intercepter(commande)
        if resultat:
            print(f"  -> {resultat}")
        else:
            print("  -> [Cortex] Appel LLM necessaire")
            cervelet.ame.impacter_budget(0.05)
            cervelet.ame.enregistrer_résultat(True)
        ame = cervelet.ame.obtenir_état_âme()
        print(f"  Humeur: {ame['humeur']} | Budget: {ame['budget_restant']:.4f}E | Anxiete: {ame['anxiete' if 'anxiete' in ame else 'anxiété']}\n")
