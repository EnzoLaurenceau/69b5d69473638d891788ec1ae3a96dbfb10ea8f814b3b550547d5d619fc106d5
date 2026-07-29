"""forge_tenant.py — identité de tenant, propagée et FERMÉE PAR DÉFAUT.

Constat qui motive ce module (mesuré) : 60 modules touchent `05_STATE`, 59 y écrivent,
et 4 seulement ont un verrou — des `threading.Lock`, qui ne protègent qu'à l'intérieur
d'un processus. En multi-tenant, chacun de ces 59 points d'écriture est une fuite
potentielle entre clients.

Plutôt que d'espérer que 59 modules pensent au cloisonnement, on l'impose en UN endroit :
`forge_store` refuse d'écrire sans tenant résolu. Ce module fournit cette identité.

PROPAGATION — attention au piège
--------------------------------
`contextvars.ContextVar` se propage automatiquement aux tâches `asyncio`, mais **PAS aux
threads d'un `ThreadPoolExecutor`** : chaque worker démarre avec un contexte VIDE. C'est
vérifié par le self-check de ce module. Comme la Forge utilise massivement les pools de
threads (`forge_swarm`…), il faut envelopper le travail avec `propagate()` :

    from .forge_tenant import propagate
    with ThreadPoolExecutor() as pool:
        pool.map(propagate(mon_travail), items)

Sans cela, le worker n'a pas de tenant et `forge_store` refuse d'écrire — échec bruyant,
jamais d'écriture dans l'espace d'un autre client.

FERMÉ PAR DÉFAUT
----------------
Sans tenant dans le contexte, `current_tenant()` LÈVE. Un appel qui oublie le scope
échoue bruyamment au lieu d'écrire dans l'espace d'un autre. Échappatoire explicite pour
l'usage local mono-utilisateur : `FORGE_SINGLE_TENANT=<id>` (même politique que
`FORGE_WEB_ALLOW_INSECURE` côté HTTP).

Self-check : python -m forge_agents.forge_tenant
"""

from __future__ import annotations

import contextvars
import functools
import logging
import os
import re
from contextlib import contextmanager

logger = logging.getLogger("ForgeTenant")

#: identifiant de tenant : minuscules, chiffres, tiret/underscore. Pas de `:` (séparateur
#: de clé Redis), pas de `/` ni `..` (traversée de chemin dans le repli fichier).
TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")

_TENANT: contextvars.ContextVar[str | None] = contextvars.ContextVar("forge_tenant", default=None)


class TenantError(RuntimeError):
    """Tenant absent, invalide, ou opération tentée hors scope."""


def validate(tenant_id: str) -> str:
    """Valide et normalise. Lève `TenantError` si l'identifiant est inacceptable."""
    if not isinstance(tenant_id, str):
        raise TenantError(f"tenant doit être une chaîne, reçu {type(tenant_id).__name__}")
    tid = tenant_id.strip().lower()
    if not TENANT_RE.match(tid):
        raise TenantError(
            f"tenant invalide: {tenant_id!r} — attendu ^[a-z0-9][a-z0-9_-]{{1,62}}$ "
            "(ni ':' ni '/' : ils casseraient l'isolation des clés et des chemins)"
        )
    return tid


def _single_tenant_fallback() -> str | None:
    raw = os.environ.get("FORGE_SINGLE_TENANT", "").strip()
    if not raw:
        return None
    try:
        return validate(raw)
    except TenantError as exc:
        logger.warning("FORGE_SINGLE_TENANT ignoré (%s)", exc)
        return None


def current_tenant() -> str:
    """Tenant courant. LÈVE si aucun n'est résolu — jamais de repli silencieux."""
    tid = _TENANT.get()
    if tid:
        return tid
    fallback = _single_tenant_fallback()
    if fallback:
        return fallback
    raise TenantError(
        "aucun tenant dans le contexte. Enveloppe l'appel dans `with tenant_scope(<id>):`, "
        "ou définis FORGE_SINGLE_TENANT=<id> pour un usage local mono-utilisateur."
    )


def current_tenant_or_none() -> str | None:
    """Variante non levante — pour la journalisation et les sondes de santé."""
    try:
        return current_tenant()
    except TenantError:
        return None


@contextmanager
def tenant_scope(tenant_id: str):
    """Fixe le tenant pour la durée du bloc, puis restaure l'état précédent.

    Ré-entrant et sûr en cas d'exception : le token de `contextvars` est toujours rendu.
    """
    tid = validate(tenant_id)
    token = _TENANT.set(tid)
    try:
        yield tid
    finally:
        _TENANT.reset(token)


def propagate(fn):
    """Enveloppe `fn` pour qu'elle s'exécute sous le tenant courant, dans un autre thread.

    Nécessaire car un `ThreadPoolExecutor` ne transmet PAS les `contextvars`. On capture
    la VALEUR du tenant à l'appel (pas l'objet `Context` : `Context.run()` n'est pas
    ré-entrant et lèverait si plusieurs workers le partageaient simultanément).
    """
    tid = current_tenant_or_none()

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if tid is None:
            return fn(*args, **kwargs)
        with tenant_scope(tid):
            return fn(*args, **kwargs)

    return wrapper


def set_tenant(tenant_id: str) -> contextvars.Token:
    """Fixe le tenant sans bloc (usage middleware). L'appelant DOIT `reset_tenant(token)`."""
    return _TENANT.set(validate(tenant_id))


def reset_tenant(token: contextvars.Token) -> None:
    _TENANT.reset(token)


if __name__ == "__main__":  # pragma: no cover
    failures = []

    def check(cond, label):
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        if not cond:
            failures.append(label)

    print("[1] Validation")
    check(validate("Acme-1") == "acme-1", "normalise en minuscules")
    for bad in ("", "a", "x" * 64, "a:b", "../etc", "A/B", "é"):
        try:
            validate(bad)
            check(False, f"rejette {bad!r}")
        except TenantError:
            check(True, f"rejette {bad!r}")

    print("\n[2] Fermé par défaut")
    os.environ.pop("FORGE_SINGLE_TENANT", None)
    try:
        current_tenant()
        check(False, "lève hors scope")
    except TenantError:
        check(True, "lève hors scope")
    check(current_tenant_or_none() is None, "variante non levante rend None")

    print("\n[3] Scope")
    with tenant_scope("acme"):
        check(current_tenant() == "acme", "scope actif")
        with tenant_scope("globex"):
            check(current_tenant() == "globex", "imbrication")
        check(current_tenant() == "acme", "restauration après imbrication")
    check(current_tenant_or_none() is None, "restauration après sortie")

    try:
        with tenant_scope("acme"):
            raise ValueError("boom")
    except ValueError:
        pass
    check(current_tenant_or_none() is None, "restauration même sur exception")

    print("\n[4] Échappatoire mono-utilisateur")
    os.environ["FORGE_SINGLE_TENANT"] = "local"
    check(current_tenant() == "local", "FORGE_SINGLE_TENANT pris en compte")
    with tenant_scope("acme"):
        check(current_tenant() == "acme", "le scope explicite prime sur l'env")
    os.environ.pop("FORGE_SINGLE_TENANT", None)

    print("\n[5] Propagation aux threads")
    from concurrent.futures import ThreadPoolExecutor

    # Le piège, vérifié plutôt qu'affirmé : un ThreadPoolExecutor ne transmet PAS
    # les contextvars — le worker démarre avec un contexte vide.
    with tenant_scope("acme"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            naive = list(pool.map(lambda _: current_tenant_or_none(), range(4)))
    check(all(g is None for g in naive),
          "contextvars NON héritées par un ThreadPoolExecutor (piège documenté)")

    with tenant_scope("acme"):
        worker = propagate(lambda _: current_tenant_or_none())
        with ThreadPoolExecutor(max_workers=2) as pool:
            got = list(pool.map(worker, range(4)))
    check(all(g == "acme" for g in got), f"propagate() rétablit le tenant ({set(got)})")

    with ThreadPoolExecutor(max_workers=2) as pool:
        outside = list(pool.map(propagate(lambda _: current_tenant_or_none()), range(2)))
    check(all(g is None for g in outside), "propagate() hors scope n'invente pas de tenant")

    print("\n" + ("ALL TESTS PASSED" if not failures else f"{len(failures)} FAILURE(S): {failures}"))
    raise SystemExit(1 if failures else 0)
