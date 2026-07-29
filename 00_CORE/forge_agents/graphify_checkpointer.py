"""
graphify_checkpointer.py — redirigé vers nexus_bridge
======================================================
graphify_index()  → nexus_bridge.memory_store()
graphify_query()  → nexus_bridge.memory_retrieve()
checkpoints       → nexus_bridge.cp_put/cp_get()

Les fonctions progress_checkpoint (DONE/TODO) et sync_findings restent ici
car elles n'ont pas d'équivalent direct dans Nexus.
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path

from .nexus_bridge import memory_store, memory_retrieve, cp_put, cp_get
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

FORGE_ROOT = Path(__file__).parent.parent.parent

# ─── Graphify API (remplacée par Nexus Memory) ───────────────────────────────

def graphify_query(query: str, max_tokens: int = 700) -> str:
    result = memory_retrieve(query, k=5, max_chars=max_tokens * 4)
    return result or f"[NEXUS] No context for: {query}"

def graphify_index(content: str, agent: str = "ORCH", cycle: int = 0) -> bool:
    key = f"{agent}-{cycle}-{datetime.datetime.now().strftime('%H%M%S%f')}"
    return memory_store(key, content, {"agent": agent, "cycle": cycle})

def ensure_gitnexus_synced() -> int:
    """No-op — gitnexus sync remplacé par Nexus VFS."""
    return 0

def sync_findings_to_graphify(findings: list[dict], cycle: int) -> int:
    indexed = 0
    for f in findings:
        if f.get("status") == "confirmed" and not f.get("graphify_indexed"):
            content = (f"## FINDING-{f.get('id','UNK')}\nAgent:{f.get('agent')}\n"
                      f"Score:{f.get('score',0)}/10\n{f.get('content','')[:400]}")
            if graphify_index(content, f.get("agent","ORCH"), cycle):
                f["graphify_indexed"] = True
                indexed += 1
    return indexed

# ─── LangGraph checkpoints → Nexus VFS ───────────────────────────────────────

def checkpoint_state_to_json(state: dict, label: str = "checkpoint") -> None:
    from .nmp_encoder import encode_state_nmp
    nmp_state = encode_state_nmp(state)
    serializable = {k: v for k, v in nmp_state.items()
                    if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
    serializable["_checkpoint_time"] = datetime.datetime.now().isoformat()

    def _default(obj):
        return str(obj.content) if hasattr(obj, "content") else (obj.value if hasattr(obj, "value") else str(obj))

    cp_put(label, serializable)
    # Aussi écrire en JSON local pour lisibilité Claude
    p = FORGE_ROOT / "05_STATE" / f"{label}.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(serializable, indent=2, ensure_ascii=False, default=_default), encoding="utf-8")

def load_last_checkpoint() -> dict:
    state = cp_get("checkpoint")
    if state:
        return state
    p = FORGE_ROOT / "05_STATE" / "checkpoint.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

# ─── Progress checkpoint (DONE/TODO) — reste local ───────────────────────────


def PROGRESS_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("progress_checkpoint.json")


def save_progress_checkpoint(session_id: str, current_task: str,
                              done: list[str], todo: list[str],
                              current_step: str = "", notes: str = "") -> None:
    PROGRESS_PATH().parent.mkdir(exist_ok=True)
    data = {
        "session_id": session_id, "current_task": current_task,
        "current_step": current_step, "done": done[-50:], "todo": todo[:50],
        "notes": notes, "updated_at": datetime.datetime.now().isoformat(),
    }
    PROGRESS_PATH().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def load_progress_checkpoint() -> dict:
    default = {"session_id": "", "current_task": "", "current_step": "", "done": [], "todo": [], "notes": ""}
    if not PROGRESS_PATH().exists():
        return default
    try:
        data = json.loads(PROGRESS_PATH().read_text(encoding="utf-8"))
        for k, v in default.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return default

def mark_step_done(step: str, next_steps: list[str] | None = None,
                    session_id: str = "", current_task: str = "", notes: str = "") -> dict:
    cp = load_progress_checkpoint()
    done = cp.get("done", [])
    todo = cp.get("todo", [])
    if step and step not in done:
        done.append(step)
    if step in todo:
        todo.remove(step)
    for s in (next_steps or []):
        if s not in todo and s not in done:
            todo.append(s)
    sid = session_id or cp.get("session_id", "")
    task = current_task or cp.get("current_task", "")
    note = notes or cp.get("notes", "")
    save_progress_checkpoint(sid, task, done, todo, current_step=step, notes=note)
    return {"session_id": sid, "current_task": task, "current_step": step,
            "done": done, "todo": todo, "notes": note}
