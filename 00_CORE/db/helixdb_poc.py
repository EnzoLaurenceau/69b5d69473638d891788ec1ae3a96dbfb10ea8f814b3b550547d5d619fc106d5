"""
helixdb_poc.py — POC : turbovec → HelixDB (évaluation, PAS une migration).
==========================================================================
Objectif (décision user 2026-06-16 = "POC d'abord") : brancher HelixDB en local,
y pousser un ÉCHANTILLON de nœuds turbovec, et comparer requêtes/perf AVANT toute
décision de migration. RIEN n'est migré, RIEN n'est supprimé de PG/Redis/turbovec.

Principe turbovec conservé : on COMPRESSE/embed le texte via turbovec AVANT de le
pousser dans Helix (compress-before-analyze). HelixDB ne remplace PAS GitNexus
(intelligence du code) — il est candidat pour la couche mémoire/vecteurs seulement.

HelixDB : base graph-vector (Rust), instance locale port 6969, SDK Python `helix-db`.

────────────────────────────────────────────────────────────────────────────────
QUOI FAIRE POUR LANCER LE POC
────────────────────────────────────────────────────────────────────────────────
  1. Installer le CLI Helix + le SDK Python :
       pip install helix-db          # SDK (import: helixdb)
       # CLI : voir docs.helix-db.com/cli/getting-started  (helix install)
  2. Démarrer une instance locale PERSISTANTE (sinon in-memory = wipe au stop) :
       helix init && helix start dev --disk
  3. Déployer le schéma POC (00_CORE/db/helix_poc_schema.hx) :  helix deploy
  4. Pousser un échantillon + interroger :
       python 00_CORE/db/helixdb_poc.py sample 30
       python 00_CORE/db/helixdb_poc.py search "openhands developer fleet"
  5. Comparer à turbovec/PG (latence, qualité de rappel) → décider.

⚠️ L'API exacte des builders d'insertion/vecteur dépend de TA version de
`helix-db`. Les fonctions _build_* ci-dessous sont marquées CONFIRM : ajuste-les
contre la doc (querying-guide/search) si l'appel échoue. Le reste (config,
extraction+compression turbovec, transport) est stable.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

HELIX_URL = os.environ.get("HELIX_URL", "http://localhost:6969")
DOC_LABEL = "ForgeDoc"  # nœud POC : {text, agent, score, vector}


class HelixUnavailable(RuntimeError):
    """SDK helix-db absent ou instance injoignable."""


# ── turbovec : compress-before (le principe reste identique) ──────────────────
def prepare_docs(texts: list[str], agent: str = "TOOLS") -> list[dict]:
    """COMPRESSE chaque texte via turbovec (embedding local) → docs prêts pour Helix.

    C'est l'étape 'compresser avant d'analyser' : on ne pousse pas le texte brut,
    on pousse sa représentation turbovec (vecteur) + un texte compact + métadonnées.
    Marche hors-ligne (embedding turbovec = local, pas de DB requise).
    """
    docs = []
    try:
        from forge_agents.turbovec_brain import get_turbovec_brain, _hash_embed
        brain = get_turbovec_brain()
        embed = getattr(brain, "embed", None) or _hash_embed  # API turbovec ou hash local
    except Exception:
        embed = None

    for t in texts:
        t = (t or "").strip()
        if not t:
            continue
        vec = None
        if embed is not None:
            try:
                v = embed(t)
                vec = list(map(float, v.tolist() if hasattr(v, "tolist") else v))
            except Exception:
                vec = None
        docs.append({
            "text": t[:2000],          # compact
            "agent": agent,
            "score": 7.5,
            "vector": vec,             # turbovec embedding (None si indispo)
        })
    return docs


def sample_from_turbovec(limit: int = 30) -> list[str]:
    """Récupère un échantillon de textes déjà dans turbovec (sinon fallback registry)."""
    try:
        from forge_agents.turbovec_brain import get_turbovec_brain
        brain = get_turbovec_brain()
        for attr in ("all_texts", "export", "dump", "nodes"):
            fn = getattr(brain, attr, None)
            if callable(fn):
                data = fn()
                texts = [d if isinstance(d, str) else d.get("text", "") for d in data]
                if texts:
                    return texts[:limit]
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    # fallback : le registry des outils (toujours dispo)
    import json
    reg = json.loads((FORGE_ROOT / "00_CORE" / "tools" / "registry.json").read_text(encoding="utf-8"))
    return [f"{t['id']}: {t.get('purpose','')}" for t in reg.get("tools", [])][:limit]


# ── HelixDB : transport ───────────────────────────────────────────────────────
def is_available() -> bool:
    """True si le SDK helix-db est importable (l'instance peut tout de même être down)."""
    try:
        import helixdb  # noqa: F401
        return True
    except Exception:
        try:
            import helix_db  # noqa: F401  (alias underscore)
            return True
        except Exception:
            return False


def _client():
    try:
        from helixdb import Client
    except Exception:
        from helix_db import Client  # type: ignore
    return Client(HELIX_URL)


def _build_insert(docs: list[dict]):
    """Construit la requête d'insertion de nœuds ForgeDoc.

    Builder confirmé via docs Helix (llms.txt) : write_batch + g().add_n(label, props).
    Un nœud par doc, bindings nommés doc0..docN. NB : l'index vectoriel sur `vector`
    se déclare côté schéma (.hx) — vérifier que la dimension turbovec (256) y colle.
    """
    from helixdb import write_batch, g
    wb = write_batch()
    names = []
    for i, d in enumerate(docs):
        props = {"text": d["text"], "agent": d["agent"], "score": float(d["score"])}
        if d.get("vector") is not None:
            props["vector"] = d["vector"]
        name = f"doc{i}"
        wb = wb.var_as(name, g().add_n(DOC_LABEL, props))
        names.append(name)
    return wb.returning(names)


def push_sample(limit: int = 30) -> dict:
    """Pousse un échantillon turbovec (compressé) dans Helix. Retourne un mini-bench."""
    if not is_available():
        raise HelixUnavailable("pip install helix-db requis (voir docstring).")
    texts = sample_from_turbovec(limit)
    docs = prepare_docs(texts)
    t0 = time.time()
    client = _client()
    batch = _build_insert(docs)
    # Envoi : selon la version du SDK, soit le client exécute le batch directement,
    # soit on passe par to_dynamic_request(). On tente les deux.
    if hasattr(batch, "to_dynamic_request"):
        client.query(batch.to_dynamic_request())
    elif hasattr(client, "query"):
        client.query(batch)
    else:
        client.send(batch)
    dt = time.time() - t0
    return {"pushed": len(docs), "with_vector": sum(d["vector"] is not None for d in docs),
            "seconds": round(dt, 3), "helix_url": HELIX_URL}


# ── Self-check (offline : valide la compression turbovec, sans Helix) ─────────
def demo():
    texts = ["please just optimize this prompt really", "openhands fleet builds tickets",
             ""]
    docs = prepare_docs(texts)
    assert len(docs) == 2, docs                       # vide ignoré
    assert all(d["text"] and d["agent"] == "TOOLS" for d in docs), docs
    s = sample_from_turbovec(5)
    assert isinstance(s, list) and len(s) >= 1, s     # fallback registry au minimum
    vec0 = docs[0]["vector"]
    print(f"helixdb_poc.demo OK | docs={len(docs)} vector_dim={len(vec0) if vec0 else 'n/a'} "
          f"| sdk_available={is_available()} | sample={len(s)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "demo"
    if cmd == "demo":
        demo()
    elif cmd == "available":
        print(f"helix-db SDK installé: {is_available()} | HELIX_URL={HELIX_URL}")
    elif cmd == "sample":
        n = int(a[1]) if len(a) > 1 else 30
        try:
            print(push_sample(n))
        except HelixUnavailable as e:
            print(f"[Helix indispo] {e}")
    elif cmd == "search" and len(a) > 1:
        print("search : implémenter via vectorSearchNodes une fois le schéma déployé "
              "(voir HELIX_POC.md).")
    else:
        print("Usage: helixdb_poc.py [demo | available | sample <n> | search <q>]")
