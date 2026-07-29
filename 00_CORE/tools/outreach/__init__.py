"""tools.outreach — CANAUX DE PROSPECTION (opt-out RGPD obligatoire sur tous).

Règle absolue : vérifier OptOutManager avant tout envoi.
Footer "STOP" obligatoire dans chaque message sortant.

Expose :
  - whatsapp_agent : WhatsApp via Claude Agent SDK (Baileys) + opt-out intégré
  - snapchat_ads   : Snapchat Ads API → Lead Gen officiel → redirect WA/TG
"""

from . import whatsapp_agent, snapchat_ads
