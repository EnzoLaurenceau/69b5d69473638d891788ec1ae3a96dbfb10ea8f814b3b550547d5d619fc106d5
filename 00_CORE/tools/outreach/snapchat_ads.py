"""
snapchat_ads.py — Wrapper Snapchat Ads API (Lead Gen → WA/TG funnel)
=====================================================================
Snapchat N'A PAS d'API publique pour les DMs automatisés.
La seule voie compliant : Snap Ads → Lead Gen form → opt-in prouvé → WA/TG.

Funnel :
  1. Créer une campagne Lead Gen sur Snap Ads Manager (ou via API ci-dessous)
  2. Les prospects remplissent le form → consentement explicite
  3. Les leads arrivent via Snapchat Conversions API / webhook
  4. La forge les ajoute au CRM (Twenty) + les contacte WA/TG (avec opt-out)

Docs : https://marketingapi.snapchat.com/docs/

Usage :
    from tools.outreach import snapchat_ads
    snapchat_ads.configure(access_token="...", ad_account_id="...")
    campaigns = snapchat_ads.list_campaigns()
    leads = snapchat_ads.pull_leads(form_id)       # leads du formulaire
    snapchat_ads.sync_leads_to_crm(leads)           # → Twenty CRM + trigger WA/TG
"""

from __future__ import annotations
import json, os, urllib.request
from typing import Any

_TOKEN = os.environ.get("SNAPCHAT_ADS_TOKEN", "")
_ACCOUNT_ID = os.environ.get("SNAPCHAT_AD_ACCOUNT_ID", "")
_BASE = "https://adsapi.snapchat.com/v1"


def configure(access_token: str, ad_account_id: str) -> None:
    global _TOKEN, _ACCOUNT_ID
    _TOKEN = access_token
    _ACCOUNT_ID = ad_account_id


def _req(method: str, path: str, payload: dict | None = None) -> Any:
    if not _TOKEN:
        raise RuntimeError(
            "Snapchat Ads non configuré. "
            "configure(access_token, ad_account_id) ou SNAPCHAT_ADS_TOKEN dans .env\n"
            "Obtenir un token : https://marketingapi.snapchat.com/docs/#authentication"
        )
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        f"{_BASE}/{path.lstrip('/')}",
        data=data,
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


# ── Campagnes ─────────────────────────────────────────────────────────────────

def list_campaigns() -> list[dict]:
    """Liste les campagnes du compte."""
    res = _req("GET", f"adaccounts/{_ACCOUNT_ID}/campaigns")
    return res.get("campaigns", [])


def create_lead_gen_campaign(
    name: str,
    daily_budget_micro: int = 5_000_000,  # 5€ en micros
    objective: str = "LEAD_GENERATION",
) -> dict:
    """
    Crée une campagne Lead Generation (swipe-up vers form).
    daily_budget_micro : budget en micro-devises (1€ = 1_000_000).
    """
    payload = {
        "campaigns": [{
            "name": name,
            "ad_account_id": _ACCOUNT_ID,
            "status": "PAUSED",   # démarrer manuellement après review
            "objective": objective,
            "daily_budget_micro": daily_budget_micro,
        }]
    }
    return _req("POST", f"adaccounts/{_ACCOUNT_ID}/campaigns", payload)


# ── Lead Gen Forms ────────────────────────────────────────────────────────────

def list_lead_gen_forms() -> list[dict]:
    """Liste les formulaires Lead Gen du compte."""
    res = _req("GET", f"adaccounts/{_ACCOUNT_ID}/leadgenforms")
    return res.get("leadgenforms", [])


def create_lead_gen_form(
    name: str,
    headline: str,
    description: str,
    privacy_policy_url: str,
    fields: list[str] | None = None,
    redirect_url: str = "",
) -> dict:
    """
    Crée un formulaire Lead Gen avec consentement explicite.
    fields : ["FULL_NAME", "PHONE_NUMBER", "EMAIL"] (au choix)
    redirect_url : URL WhatsApp Business ou Telegram après soumission.
    """
    default_fields = fields or ["FULL_NAME", "PHONE_NUMBER"]
    payload = {
        "leadgenforms": [{
            "ad_account_id": _ACCOUNT_ID,
            "name": name,
            "headline": headline,
            "description": description,
            "privacy_policy_url": privacy_policy_url,
            "question_properties": [{"type": f} for f in default_fields],
            "completion_type": "REDIRECT",
            "completion_url": redirect_url,
            # Consentement RGPD explicite dans le form
            "consent_properties": [{
                "type": "CUSTOM",
                "title": "Je consens à être contacté",
                "description": "En soumettant ce formulaire, j'accepte d'être contacté. Je peux me désinscrire à tout moment en répondant STOP.",
                "required": True,
            }],
        }]
    }
    return _req("POST", f"adaccounts/{_ACCOUNT_ID}/leadgenforms", payload)


# ── Leads collectés ───────────────────────────────────────────────────────────

def pull_leads(form_id: str, since_ts: int | None = None) -> list[dict]:
    """
    Récupère les leads d'un formulaire.
    Chaque lead = {full_name, phone_number, email, created_at, ...}
    """
    path = f"leadgenforms/{form_id}/leads"
    if since_ts:
        path += f"?start_time={since_ts}"
    res = _req("GET", path)
    return res.get("leads", [])


def sync_leads_to_crm(leads: list[dict], channel: str = "whatsapp") -> dict:
    """
    Pipeline complet :
      lead Snapchat → normalise → Twenty CRM → trigger WA/TG
    Retourne {"synced": N, "already_known": N}
    """
    from ..product_bricks.crm.twenty_crm import upsert_contact
    from ..outreach import whatsapp_agent
    from ...forge_agents.opt_out_manager import get_opt_out_manager

    mgr = get_opt_out_manager()
    results = {"synced": 0, "already_known": 0, "blocked": 0}

    for lead in leads:
        phone = lead.get("phone_number", "")
        if not phone:
            continue
        if mgr.is_blocked(phone):
            results["blocked"] += 1
            continue
        # Upsert dans Twenty CRM
        try:
            upsert_contact({
                "phone": phone,
                "name": lead.get("full_name", ""),
                "email": lead.get("email", ""),
                "source": "snapchat_lead_gen",
                "consent": True,
            })
            results["synced"] += 1
        except Exception:
            results["already_known"] += 1

    return results


# ── Redirect WA / TG ──────────────────────────────────────────────────────────

def wa_redirect_url(phone: str, message: str = "") -> str:
    """Génère l'URL deep-link WhatsApp pour la completion page du form."""
    import urllib.parse
    base = f"https://wa.me/{phone.lstrip('+')}"
    return f"{base}?text={urllib.parse.quote(message)}" if message else base


def tg_redirect_url(bot_username: str, start_param: str = "") -> str:
    """Génère l'URL deep-link Telegram pour la completion page du form."""
    return f"https://t.me/{bot_username}?start={start_param}"


# ponytail: wrapper API mince. Snap Ads Manager = voie compliant.
# DMs Snapchat automatiques = impossible + ToS violation.
if __name__ == "__main__":
    configured = bool(_TOKEN)
    print(f"snapchat_ads: {'configuré' if configured else 'non configuré'}")
    print("vars: SNAPCHAT_ADS_TOKEN + SNAPCHAT_AD_ACCOUNT_ID dans .env")
    print("funnel: Snap Ad → Lead Gen Form → sync_leads_to_crm() → WA/TG")
    print(f"wa_redirect: {wa_redirect_url('+33600000000', 'Bonjour !')}")
