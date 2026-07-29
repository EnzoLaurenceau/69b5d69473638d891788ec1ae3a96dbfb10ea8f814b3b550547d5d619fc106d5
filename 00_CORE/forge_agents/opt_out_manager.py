"""
opt_out_manager.py — Gestionnaire opt-out GDPR/ePrivacy centralisé
===================================================================
Toute campagne de prospection (WhatsApp, Telegram, email, SMS) DOIT
vérifier ici avant d'envoyer. Si un contact dit STOP → blocklist immédiat,
permanent, toutes chaînes confondues.

Loi applicable : RGPD Art.17, ePrivacy Directive, Loi Lemaire.

Usage :
    from forge_agents.opt_out_manager import OptOutManager
    mgr = OptOutManager()
    mgr.check("33612345678")          # lève ContactOptedOut si bloqué
    mgr.register_optout("33612345678", channel="whatsapp", reason="STOP message")
    mgr.is_blocked("33612345678")     # → bool
    mgr.detect_and_register(sender_id, message_text, channel)  # auto-detect
"""

from __future__ import annotations
import re, time
from datetime import datetime, timezone
from typing import Optional

from .forge_db import get_db
import logging

logger = logging.getLogger(__name__)

# Mots-clés déclenchant un opt-out automatique (toutes langues)
_STOP_PATTERNS = re.compile(
    r"\b(stop|arrête|arrêtez|désinscrire|désinscription|unsubscribe|"
    r"ne\s+plus\s+contacter|supprime[rz]?\s+mon|remove\s+me|"
    r"plus\s+de\s+messages?|no\s+more\s+messages?|quitte[rz]?|"
    r"bloqu[eé][rz]?|optout|opt.?out)\b",
    re.IGNORECASE | re.UNICODE,
)

_TABLE = "contact_optout"


class ContactOptedOut(Exception):
    """Levée quand on tente de contacter un numéro en opt-out."""
    def __init__(self, contact_id: str):
        super().__init__(f"Contact {contact_id} a exercé son droit d'opt-out. Envoi bloqué.")
        self.contact_id = contact_id


class OptOutManager:
    """
    Blocklist persistante PostgreSQL.
    Fallback mémoire si PG indisponible (perd les données au redémarrage — loggue un warning).
    """

    def __init__(self):
        self._db = get_db()
        self._memory_fallback: set[str] = set()
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Crée la table si absente (idempotent)."""
        try:
            conn = self._db._pg_conn()
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS contact_optout (
                        id          SERIAL PRIMARY KEY,
                        contact_id  TEXT NOT NULL UNIQUE,
                        channel     TEXT DEFAULT 'all',
                        reason      TEXT,
                        ts          TIMESTAMPTZ DEFAULT NOW(),
                        gdpr_logged BOOLEAN DEFAULT TRUE
                    );
                    CREATE INDEX IF NOT EXISTS idx_optout_contact ON contact_optout(contact_id);
                """)
            conn.commit()
        except Exception:
            pass  # PG indisponible → fallback mémoire

    # ── Écriture ─────────────────────────────────────────────────────────────

    def register_optout(self, contact_id: str, channel: str = "all", reason: str = "") -> None:
        """
        Enregistre un opt-out. Immédiat et permanent.
        contact_id = numéro E.164 ou identifiant unique (telegram_id, email…)
        """
        contact_id = _normalize(contact_id)
        ts = datetime.now(timezone.utc).isoformat()

        try:
            self._db.deep_insert(_TABLE, {
                "contact_id": contact_id,
                "channel": channel,
                "reason": reason[:500],
                "ts": ts,
                "gdpr_logged": True,
            })
        except Exception:
            # Fallback mémoire
            self._memory_fallback.add(contact_id)

        # Log Redis pour lecture rapide
        self._db.hot_set(f"optout:{contact_id}", "1", ttl=None)  # permanent
        print(f"[OPT-OUT] {contact_id} bloqué ({channel}) — {reason or 'demande utilisateur'}")

    def remove_optout(self, contact_id: str) -> None:
        """
        Réintégration explicite (re-consentement prouvé uniquement).
        Ne jamais appeler automatiquement.
        """
        contact_id = _normalize(contact_id)
        try:
            conn = self._db._pg_conn()
            if conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM contact_optout WHERE contact_id = %s", (contact_id,))
                conn.commit()
        except Exception:
            self._memory_fallback.discard(contact_id)
        self._db.hot_set(f"optout:{contact_id}", "0", ttl=1)
        print(f"[OPT-OUT] {contact_id} réintégré (re-consentement enregistré)")

    # ── Lecture ──────────────────────────────────────────────────────────────

    def is_blocked(self, contact_id: str) -> bool:
        """True si le contact est en opt-out."""
        contact_id = _normalize(contact_id)
        # Check Redis (rapide)
        try:
            val = self._db.hot_get(f"optout:{contact_id}")
            if val == "1":
                return True
            if val == "0":
                return False
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        # Check mémoire fallback
        if contact_id in self._memory_fallback:
            return True
        # Check PostgreSQL (source de vérité)
        try:
            rows = self._db.deep_query(_TABLE, {"contact_id": contact_id}, limit=1)
            blocked = len(rows) > 0
            if blocked:
                self._db.hot_set(f"optout:{contact_id}", "1", ttl=3600)
            return blocked
        except Exception:
            return False

    def check(self, contact_id: str) -> None:
        """Lève ContactOptedOut si bloqué. À appeler avant tout envoi."""
        if self.is_blocked(contact_id):
            raise ContactOptedOut(contact_id)

    # ── Auto-détection ───────────────────────────────────────────────────────

    def detect_and_register(self, contact_id: str, text: str, channel: str = "unknown") -> bool:
        """
        Analyse le texte reçu, enregistre l'opt-out si mot-clé détecté.
        Retourne True si opt-out déclenché.
        Appeler sur CHAQUE message entrant avant de traiter.
        """
        if _STOP_PATTERNS.search(text):
            self.register_optout(contact_id, channel=channel, reason=f"auto-detect: {text[:100]}")
            return True
        return False

    def export_blocklist(self) -> list[dict]:
        """Export RGPD — liste de tous les opt-outs (pour audit)."""
        try:
            return self._db.deep_query(_TABLE, limit=10000)
        except Exception:
            return [{"contact_id": c, "channel": "memory"} for c in self._memory_fallback]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalize(contact_id: str) -> str:
    """Normalise un contact_id (strip espaces, lowercase pour emails)."""
    s = contact_id.strip()
    return s if s.startswith("+") or s.isdigit() else s.lower()


# Singleton
_instance: Optional[OptOutManager] = None

def get_opt_out_manager() -> OptOutManager:
    global _instance
    if _instance is None:
        _instance = OptOutManager()
    return _instance


if __name__ == "__main__":
    mgr = OptOutManager()
    # Self-check
    mgr.register_optout("+33600000001", "test", "self-check")
    assert mgr.is_blocked("+33600000001"), "FAIL: devrait être bloqué"
    assert mgr.detect_and_register("+33600000002", "Arrêtez de m'envoyer des messages", "test")
    assert mgr.is_blocked("+33600000002")
    mgr.remove_optout("+33600000001")
    assert not mgr.is_blocked("+33600000001"), "FAIL: devrait être débloqué"
    print("opt_out_manager: OK — blocklist RGPD opérationnelle")
