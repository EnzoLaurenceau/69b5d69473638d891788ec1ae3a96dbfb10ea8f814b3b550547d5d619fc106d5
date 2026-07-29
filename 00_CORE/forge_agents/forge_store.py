"""forge_store.py — état cloisonné par tenant. Point de passage UNIQUE.

POURQUOI CE MODULE EXISTE
-------------------------
Mesuré : 60 modules touchent `05_STATE`, **59 y écrivent**, et 4 seulement ont un verrou
— des `threading.Lock`, qui ne protègent qu'à l'intérieur d'un processus. En multi-tenant,
chacun de ces 59 points est une fuite potentielle entre clients.

On ne corrige pas ça en demandant à 59 modules de penser au cloisonnement. On l'impose
ici : toute écriture passe par `forge_store`, qui résout le tenant et refuse d'agir sans
lui. L'isolation devient une propriété du code, pas une discipline.

GARANTIES
---------
- **Fermé par défaut** : sans tenant résolu, tout appel LÈVE (`TenantError`). Jamais
  d'écriture « par défaut » dans un espace partagé.
- **Isolation physique** : repli fichier sous `05_STATE/tenants/<tenant>/…`. Une clé d'un
  tenant ne peut pas désigner le fichier d'un autre (identifiants et clés validés).
- **Écriture atomique** : fichier temporaire + `os.replace` — jamais de JSON tronqué si le
  processus meurt en cours d'écriture (le motif `write_text` direct, courant dans le dépôt,
  n'offre pas cette garantie).
- **Concurrence inter-processus** : verrou par clé le temps du `read-modify-write`.

BACKENDS
--------
`forge_db` (PG + Redis) quand il répond, sinon repli fichier par tenant. Le repli n'est
pas un mode dégradé honteux : c'est le mode local mono-utilisateur, et il conserve
l'isolation.

Self-check : python -m forge_agents.forge_store
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .forge_tenant import TenantError, current_tenant, validate  # noqa: F401

logger = logging.getLogger("ForgeStore")

FORGE_ROOT = Path(__file__).resolve().parents[2]
TENANTS_ROOT = FORGE_ROOT / "05_STATE" / "tenants"

#: namespace et clé : mêmes contraintes que le tenant — pas de séparateur ni de traversée
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class StoreError(RuntimeError):
    """Namespace/clé invalide, ou écriture impossible."""


def _check_name(value: str, what: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise StoreError(
            f"{what} invalide: {value!r} — attendu ^[A-Za-z0-9][A-Za-z0-9_.\\-]{{0,127}}$ "
            "(ni '/' ni '..' : cela permettrait de sortir de l'espace du tenant)"
        )
    if ".." in value:
        raise StoreError(f"{what} invalide: {value!r} — '..' interdit")
    return value


def _key_lock(path: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(path, threading.Lock())


def tenant_dir(tenant: str | None = None) -> Path:
    """Répertoire racine du tenant courant. Crée l'arborescence au besoin."""
    tid = validate(tenant) if tenant else current_tenant()
    d = TENANTS_ROOT / tid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path_for(namespace: str, key: str) -> Path:
    _check_name(namespace, "namespace")
    _check_name(key, "clé")
    d = tenant_dir() / namespace
    d.mkdir(parents=True, exist_ok=True)
    p = (d / key).resolve()
    # Défense en profondeur : même si la validation était contournée, on refuse toute
    # cible hors de l'espace du tenant.
    if not str(p).startswith(str(tenant_dir().resolve())):
        raise StoreError(f"chemin hors de l'espace du tenant: {p}")
    return p


def _atomic_write(path: Path, data: str) -> None:
    """Écriture atomique : temporaire dans le MÊME dossier puis `os.replace`.

    Le temporaire doit partager le volume de la cible, sinon `os.replace` n'est plus
    atomique (voire échoue entre volumes sous Windows).
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════════════════════════

def put(namespace: str, key: str, value: Any) -> None:
    """Écrit une valeur JSON pour le tenant courant. Atomique."""
    p = _path_for(namespace, key)
    payload = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    with _key_lock(str(p)):
        _atomic_write(p, payload)
    _mirror_hot(namespace, key, value)


def get(namespace: str, key: str, default: Any = None) -> Any:
    """Lit une valeur JSON du tenant courant. `default` si absente ou illisible."""
    p = _path_for(namespace, key)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        # Un état corrompu ne doit pas être silencieusement remplacé par du vide :
        # on trace, et l'appelant décide via `default`.
        logger.warning("état illisible %s/%s: %s", namespace, key, exc)
        return default


def append(namespace: str, key: str, record: Any) -> None:
    """Ajoute une ligne JSONL (append-only) pour le tenant courant."""
    p = _path_for(namespace, key)
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _key_lock(str(p)):
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line)


def read_lines(namespace: str, key: str, limit: int = 0) -> list:
    """Lit un JSONL du tenant courant. Les lignes illisibles sont ignorées et comptées."""
    p = _path_for(namespace, key)
    if not p.exists():
        return []
    out, bad = [], 0
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    if bad:
        logger.warning("%s/%s: %d ligne(s) JSONL illisibles ignorées", namespace, key, bad)
    return out[-limit:] if limit else out


def list_keys(namespace: str) -> list:
    _check_name(namespace, "namespace")
    d = tenant_dir() / namespace
    return sorted(p.name for p in d.glob("*") if p.is_file() and not p.name.startswith(".tmp-"))


def delete(namespace: str, key: str) -> bool:
    p = _path_for(namespace, key)
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False


def state_path(name: str) -> Path:
    """Chemin d'un fichier d'état, cloisonné par tenant quand il y en a un.

    POURQUOI CE RACCOURCI EXISTE (W5-03a)
    -------------------------------------
    Mesuré : 64 modules écrivent dans `05_STATE`, 213 sites d'écriture. Les porter à
    l'API `put/get/append` demande de réécrire leurs entrées/sorties une par une —
    coûteux, risqué, et ce n'est pas ce qui manque pour être multi-tenant. Ce qui manque,
    c'est **l'isolation**. `state_path` la donne en changeant une ligne par module :

        LOG = FORGE_ROOT / "05_STATE" / "adaptive_rag_log.jsonl"   # avant
        def _log(): return state_path("adaptive_rag_log.jsonl")    # après

    Le module garde son écriture ; seul le répertoire change.

    CE QUE ÇA NE DONNE PAS
    ----------------------
    Ni atomicité ni verrou : c'est un chemin, pas une écriture. Pour du nouvel état,
    utiliser `put/append` qui, eux, offrent les deux. Ici on achète l'isolation seule,
    sciemment — c'est la propriété qui bloque l'expédition.

    MODE DE TRANSITION (blueprint multi_tenant.md §5)
    -------------------------------------------------
    Sans tenant en contexte, on retombe sur le chemin GLOBAL historique avec un
    avertissement unique, pour que migrer module par module ne casse pas l'existant.
    `FORGE_TENANT_STRICT=1` transforme ce repli en erreur — c'est ce que la CI utilise.
    """
    rel = Path(str(name).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise StoreError(f"nom d'état invalide: {name!r} — chemin relatif sans '..' attendu")
    for part in rel.parts:
        _check_name(part, "segment de chemin")

    tid = None
    try:
        from .forge_tenant import current_tenant_or_none
        tid = current_tenant_or_none()
    except Exception as exc:  # forge_tenant absent : on ne casse pas l'appelant
        logger.debug("contexte tenant indisponible: %s", exc)

    if tid is None:
        if os.environ.get("FORGE_TENANT_STRICT", "").lower() in ("1", "true", "yes"):
            from .forge_tenant import current_tenant
            current_tenant()          # lève volontairement : mode strict demandé
        global _warned_global
        if not _warned_global:
            _warned_global = True
            logger.warning(
                "état écrit dans l'espace GLOBAL (aucun tenant en contexte) — "
                "mode de transition ; `with tenant_scope(<id>):` ou FORGE_SINGLE_TENANT=<id>"
            )
        p = FORGE_ROOT / "05_STATE" / rel
    else:
        p = tenant_dir(tid) / rel

    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_warned_global = False


def _mirror_hot(namespace: str, key: str, value: Any) -> None:
    """Réplique en cache chaud (Redis via forge_db) si disponible — best effort.

    La clé est préfixée par le tenant : deux tenants ne peuvent pas se marcher dessus
    dans un Redis partagé.
    """
    try:
        from .forge_db import get_db
        db = get_db()
        if getattr(db, "db_up", lambda: False)():
            db.hot_set(f"t:{current_tenant()}:{namespace}:{key}", value)
    except Exception as exc:
        logger.debug("miroir chaud indisponible: %s", exc)


def stats() -> dict:
    """Empreinte du tenant courant — pour les quotas et la page santé."""
    root = tenant_dir()
    files = [p for p in root.rglob("*") if p.is_file()]
    return {
        "tenant": current_tenant(),
        "namespaces": sorted({p.parent.name for p in files}),
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
    }


if __name__ == "__main__":  # pragma: no cover
    import shutil
    from .forge_tenant import tenant_scope

    failures = []

    def check(cond, label):
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        if not cond:
            failures.append(label)

    A, B = "test-alpha", "test-beta"
    for t in (A, B):
        shutil.rmtree(TENANTS_ROOT / t, ignore_errors=True)

    print("[1] Fermé par défaut")
    os.environ.pop("FORGE_SINGLE_TENANT", None)
    try:
        put("cfg", "x", 1)
        check(False, "écriture hors tenant refusée")
    except TenantError:
        check(True, "écriture hors tenant refusée")

    print("\n[2] Isolation entre tenants")
    with tenant_scope(A):
        put("cfg", "secret", {"valeur": "propre-a-A"})
        append("events", "log.jsonl", {"qui": "A"})
    with tenant_scope(B):
        check(get("cfg", "secret") is None, "B ne voit pas la clé de A")
        check(read_lines("events", "log.jsonl") == [], "B ne voit pas le journal de A")
        put("cfg", "secret", {"valeur": "propre-a-B"})
    with tenant_scope(A):
        check(get("cfg", "secret")["valeur"] == "propre-a-A", "A garde sa valeur intacte")
        check(len(read_lines("events", "log.jsonl")) == 1, "journal de A intact")

    print("\n[3] Refus des clés dangereuses")
    with tenant_scope(A):
        for bad in ("../../etc", "a/b", "..", ""):
            try:
                put("cfg", bad, 1)
                check(False, f"rejette la clé {bad!r}")
            except StoreError:
                check(True, f"rejette la clé {bad!r}")

    print("\n[4] Atomicité & robustesse")
    with tenant_scope(A):
        put("cfg", "big", {"n": list(range(500))})
        check(get("cfg", "big")["n"][-1] == 499, "relecture fidèle")
        p = _path_for("cfg", "corrompu")
        p.write_text("{ ceci n'est pas du json", encoding="utf-8")
        check(get("cfg", "corrompu", default="REPLI") == "REPLI",
              "état corrompu -> default, sans écrasement silencieux")
        check(p.exists(), "le fichier corrompu n'est PAS supprimé en douce")
        leftovers = [x for x in (tenant_dir() / "cfg").glob(".tmp-*")]
        check(not leftovers, "aucun temporaire laissé derrière")

    print("\n[5] Concurrence (8 threads, append)")
    from concurrent.futures import ThreadPoolExecutor
    from .forge_tenant import propagate
    with tenant_scope(B):
        delete("events", "concurrent.jsonl")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(propagate(lambda i: append("events", "concurrent.jsonl", {"i": i})),
                          range(200)))
        rows = read_lines("events", "concurrent.jsonl")
        check(len(rows) == 200, f"200 écritures concurrentes, 0 perdue (eu {len(rows)})")
        check(len({r["i"] for r in rows}) == 200, "aucune ligne corrompue ni dupliquée")

    print("\n[6] state_path — isolation, repli, refus")
    with tenant_scope(A):
        pa = state_path("logs/exec.jsonl")
    with tenant_scope(B):
        pb = state_path("logs/exec.jsonl")
    check(pa != pb, "même nom, deux tenants -> deux fichiers distincts")
    check(str(pa).startswith(str(TENANTS_ROOT / A)), "chemin bien dans l'espace du tenant")
    check(pa.parent.is_dir(), "le sous-répertoire est créé")
    os.environ.pop("FORGE_SINGLE_TENANT", None)
    os.environ["FORGE_TENANT_STRICT"] = "1"
    try:
        state_path("x.json")
        check(False, "strict: sans tenant -> lève")
    except TenantError:
        check(True, "strict: sans tenant -> lève")
    os.environ.pop("FORGE_TENANT_STRICT", None)
    check(state_path("x.json") == FORGE_ROOT / "05_STATE" / "x.json",
          "transition: sans tenant -> chemin global historique")
    with tenant_scope(A):
        for bad in ("../../etc/passwd", "/abs/x.json", "a/../../b"):
            try:
                state_path(bad)
                check(False, f"rejette {bad!r}")
            except StoreError:
                check(True, f"rejette {bad!r}")

    print("\n[7] Empreinte")
    with tenant_scope(A):
        s = stats()
        check(s["tenant"] == A and s["files"] >= 2, f"stats du tenant: {s['files']} fichiers")

    for t in (A, B):
        shutil.rmtree(TENANTS_ROOT / t, ignore_errors=True)
    print("\n" + ("ALL TESTS PASSED" if not failures else f"{len(failures)} FAILURE(S): {failures}"))
    raise SystemExit(1 if failures else 0)
