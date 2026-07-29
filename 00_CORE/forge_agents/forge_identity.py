"""forge_identity.py — comptes et jetons : QUI est le tenant courant.

LE PROBLÈME
-----------
`WEB_SECRET` est un secret **partagé unique**. Il autorise, mais il n'identifie personne :
impossible de dire quel client a fait quoi, donc impossible de cloisonner ou de facturer.
Le multi-tenant a besoin d'une identité, pas seulement d'un mot de passe.

CE QUE FAIT CE MODULE
---------------------
- un registre de tenants (`05_STATE/identity/tenants.json`), volontairement HORS de
  l'espace par tenant : il faut pouvoir résoudre l'identité *avant* de savoir qui on est ;
- des jetons **jamais stockés en clair** — seul leur SHA-256 est conservé ;
- une résolution jeton → tenant en **temps constant** (`hmac.compare_digest`), pour ne pas
  fuiter d'information par le temps de réponse.

SUR LE HACHAGE
--------------
SHA-256 sans sel ni facteur de coût est le bon choix **ici** : les jetons sont générés par
`secrets.token_urlsafe(32)`, soit ~256 bits d'entropie. Une attaque par dictionnaire ou
force brute est hors de portée, contrairement à un mot de passe choisi par un humain — qui
exigerait, lui, bcrypt/argon2. Si un jour des mots de passe entrent ici, ce choix doit changer.

COMPATIBILITÉ
-------------
`WEB_SECRET` continue de fonctionner et résout vers le tenant `DEFAULT_TENANT`. Sans cela,
la migration casserait toute installation existante.

CLI :
    python -m forge_agents.forge_identity list
    python -m forge_agents.forge_identity create <tenant_id> [libellé]
    python -m forge_agents.forge_identity revoke <tenant_id>
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from .forge_tenant import TenantError, validate

logger = logging.getLogger("ForgeIdentity")

FORGE_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = FORGE_ROOT / "05_STATE" / "identity" / "tenants.json"
DEFAULT_TENANT = "default"

_lock = threading.Lock()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load() -> dict:
    try:
        # `utf-8-sig` et non `utf-8` : sur cette plateforme, tout ce qui écrit le registre
        # depuis PowerShell (`Set-Content`, `Out-File`) y colle un BOM. Avec `utf-8` strict,
        # `json.loads` échoue sur le tout premier caractère, `_load` lève, et TOUTE
        # résolution de jeton retourne 401 — l'API entière devient inaccessible pour un
        # octet invisible. `utf-8-sig` lit indifféremment avec ou sans BOM ; l'écriture,
        # elle, reste en `utf-8` nu (cf. `_save`).
        return json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"tenants": {}}
    except (OSError, json.JSONDecodeError) as exc:
        # Registre illisible : on REFUSE de repartir d'un registre vide, ce qui
        # reviendrait à révoquer tout le monde en silence.
        raise TenantError(f"registre d'identité illisible ({REGISTRY}): {exc}") from exc


def _save(data: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, REGISTRY)


def create_tenant(tenant_id: str, label: str = "") -> str:
    """Crée un tenant et retourne son jeton EN CLAIR — affiché une seule fois.

    Le clair n'est jamais persisté : si l'appelant le perd, il faut en régénérer un.
    """
    tid = validate(tenant_id)
    token = secrets.token_urlsafe(32)
    with _lock:
        data = _load()
        if tid in data["tenants"]:
            raise TenantError(f"le tenant {tid!r} existe déjà — utilise rotate_token()")
        data["tenants"][tid] = {
            "label": label or tid,
            "token_sha256": _hash(token),
            "created": time.time(),
            "active": True,
        }
        _save(data)
    logger.info("tenant créé: %s", tid)
    return token


def rotate_token(tenant_id: str) -> str:
    """Régénère le jeton d'un tenant existant. L'ancien cesse immédiatement d'être valide."""
    tid = validate(tenant_id)
    token = secrets.token_urlsafe(32)
    with _lock:
        data = _load()
        if tid not in data["tenants"]:
            raise TenantError(f"tenant inconnu: {tid!r}")
        data["tenants"][tid]["token_sha256"] = _hash(token)
        data["tenants"][tid]["rotated"] = time.time()
        _save(data)
    return token


def revoke(tenant_id: str) -> bool:
    tid = validate(tenant_id)
    with _lock:
        data = _load()
        if tid not in data["tenants"]:
            return False
        data["tenants"][tid]["active"] = False
        _save(data)
    return True


def resolve_token(token: str | None) -> str | None:
    """Jeton → tenant, en temps constant. `None` si inconnu, inactif, ou vide.

    La comparaison parcourt TOUS les tenants sans court-circuit : le temps de réponse ne
    doit pas révéler l'existence d'un compte.
    """
    if not token:
        return None
    digest = _hash(token)
    try:
        data = _load()
    except TenantError as exc:
        logger.error("résolution impossible: %s", exc)
        return None

    found: str | None = None
    for tid, rec in data.get("tenants", {}).items():
        if hmac.compare_digest(digest, rec.get("token_sha256", "")) and rec.get("active", True):
            found = tid          # pas de `break` : temps constant
    if found:
        return found

    # Repli de compatibilité : WEB_SECRET historique → tenant par défaut.
    web_secret = os.environ.get("WEB_SECRET", "").strip()
    if web_secret and web_secret != "forge-dev-token" and hmac.compare_digest(token, web_secret):
        return DEFAULT_TENANT
    return None


def list_tenants() -> list:
    """Tenants connus — sans aucun secret."""
    data = _load()
    return sorted(
        ({"tenant": tid, "label": r.get("label", tid), "active": r.get("active", True),
          "created": r.get("created")} for tid, r in data.get("tenants", {}).items()),
        key=lambda r: r["tenant"],
    )


def ensure_default() -> None:
    """Crée le tenant `default` s'il manque — pour que l'existant continue de tourner."""
    data = _load()
    if DEFAULT_TENANT not in data.get("tenants", {}):
        with _lock:
            data = _load()
            data.setdefault("tenants", {})[DEFAULT_TENANT] = {
                "label": "tenant par défaut (compatibilité WEB_SECRET)",
                "token_sha256": "",          # aucun jeton propre : passe par WEB_SECRET
                "created": time.time(),
                "active": True,
            }
            _save(data)


if __name__ == "__main__":  # pragma: no cover
    import sys

    args = sys.argv[1:]
    if args and args[0] == "create":
        tok = create_tenant(args[1], " ".join(args[2:]))
        print(f"tenant {args[1]} créé.\nJETON (affiché UNE seule fois) : {tok}")
    elif args and args[0] == "revoke":
        print("révoqué" if revoke(args[1]) else "tenant inconnu")
    elif args and args[0] == "list":
        for r in list_tenants():
            print(f"  {r['tenant']:<20}{'actif' if r['active'] else 'REVOQUE':<10}{r['label']}")
    else:
        # self-check
        failures = []

        def check(cond, label):
            print(f"  {'PASS' if cond else 'FAIL'}  {label}")
            if not cond:
                failures.append(label)

        backup = REGISTRY.read_text(encoding="utf-8") if REGISTRY.exists() else None
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text('{"tenants": {}}', encoding="utf-8")
        os.environ.pop("WEB_SECRET", None)
        try:
            print("[1] Création & résolution")
            t_a = create_tenant("acme", "Acme Corp")
            t_b = create_tenant("globex", "Globex")
            check(resolve_token(t_a) == "acme", "jeton A → tenant A")
            check(resolve_token(t_b) == "globex", "jeton B → tenant B")
            check(resolve_token("n-importe-quoi") is None, "jeton inconnu → None")
            check(resolve_token(None) is None, "jeton vide → None")
            check(t_a != t_b and len(t_a) > 30, "jetons distincts et à forte entropie")

            print("\n[2] Aucun secret en clair sur disque")
            raw = REGISTRY.read_text(encoding="utf-8")
            check(t_a not in raw and t_b not in raw, "les jetons ne sont PAS stockés en clair")
            check("token_sha256" in raw, "seul le SHA-256 est conservé")

            print("\n[3] Rotation & révocation")
            t_a2 = rotate_token("acme")
            check(resolve_token(t_a2) == "acme", "le nouveau jeton fonctionne")
            check(resolve_token(t_a) is None, "l'ancien jeton est invalidé")
            revoke("globex")
            check(resolve_token(t_b) is None, "un tenant révoqué ne résout plus")

            print("\n[4] Compatibilité WEB_SECRET")
            os.environ["WEB_SECRET"] = "un-vrai-secret-de-prod"
            check(resolve_token("un-vrai-secret-de-prod") == DEFAULT_TENANT,
                  "WEB_SECRET → tenant par défaut")
            os.environ["WEB_SECRET"] = "forge-dev-token"
            check(resolve_token("forge-dev-token") is None,
                  "le jeton de dev par défaut ne donne AUCUNE identité")
            os.environ.pop("WEB_SECRET", None)

            print("\n[5] Registre corrompu")
            REGISTRY.write_text("{ pas du json", encoding="utf-8")
            check(resolve_token(t_a2) is None, "registre illisible → refus (pas d'accès)")
            try:
                list_tenants()
                check(False, "lève sur registre corrompu")
            except TenantError:
                check(True, "lève sur registre corrompu (pas de reset silencieux)")
        finally:
            if backup is not None:
                REGISTRY.write_text(backup, encoding="utf-8")
            else:
                REGISTRY.unlink(missing_ok=True)

        print("\n" + ("ALL TESTS PASSED" if not failures else f"{len(failures)} FAILURE(S): {failures}"))
        raise SystemExit(1 if failures else 0)
