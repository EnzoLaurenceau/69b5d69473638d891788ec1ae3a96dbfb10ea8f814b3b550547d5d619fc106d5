"""
test_aaos_wave.py — Self-check de la vague AAOS (09_TASKS/aaos_devops_plan.md)
Couvre : fingerprint 63/64, dedup 65, replacement 78, classifier 79, savings 84,
cost comparison 87, quality trigger 92, dataset health 94/95/96, memory 100,
regression guard 101, registry 59, hook forge_call zero-redundancy.
Aucun appel LLM réel (stub). Exécution : python test_aaos_wave.py (depuis 00_CORE/).
"""
import json
import shutil
import sys
import time
import py_compile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
FORGE_ROOT = Path(__file__).parent.parent
TMP = FORGE_ROOT / "05_STATE" / "_aaos_selftest_tmp"

passed = []


def check(name, fn):
    fn()
    passed.append(name)
    print(f"  OK  {name}")


# ── 1. Syntaxe de tous les fichiers modifiés ─────────────────────────────────
def t_syntax():
    for f in [
        "00_CORE/forge_agents/forge_fingerprint.py",
        "00_CORE/forge_agents/forge_llm.py",
        "00_CORE/forge_agents/token_tracker.py",
        "00_CORE/forge_agents/dataset_rag.py",
        "00_CORE/forge_agents/agent_nodes.py",
        "00_CORE/forge_agents/forge_system_registry.py",
        "09_WEB/server.py",
    ]:
        py_compile.compile(str(FORGE_ROOT / f), doraise=True)


# ── 2. Fingerprint 63/64/65/78/79/87 ─────────────────────────────────────────
def t_fingerprint():
    from forge_agents.forge_fingerprint import (
        FingerprintStore, make_fingerprint, dedupe_chunks, classify_task,
        compare_costs, fingerprint_enabled)
    assert fingerprint_enabled()
    s = FingerprintStore(TMP / "fp.json")
    fp = make_fingerprint("extract emails", "", "free", "x")
    assert s.check(fp) is None
    s.record(fp, "result", tokens=100, latency=1.0, task="extract emails")
    assert s.check(fp)["result"] == "result"
    s.check(fp); s.check(fp)
    assert s.detect_repetitive(3)[0]["hits"] >= 3
    assert dedupe_chunks(["a", "a", "b"]) == ["a", "b"]
    assert classify_task("parse and count csv rows")["can_be_scripted"]
    assert classify_task("conçois l'architecture et évalue les trade-offs")["requires_reasoning"]
    assert compare_costs("compte les lignes csv")["route"] in ("local", "cache")


# ── 3. Token tracker savings 84 ──────────────────────────────────────────────
def t_savings():
    from forge_agents.token_tracker import TokenTracker
    t = TokenTracker()
    t.add_saving(tokens=500, cost=0.01, latency_ms=800)
    t.add_saving(tokens=300)
    ss = t.savings_summary()
    assert ss == {"tokens_saved": 800, "money_saved": 0.01,
                  "latency_saved_ms": 800, "calls_avoided": 2}
    t.reset_session("s2")
    assert t.savings_summary()["calls_avoided"] == 0


# ── 4. Dataset quality 94/95/96/100/101 + gap 92 ─────────────────────────────
def t_dataset_quality():
    import forge_agents.dataset_rag as dr
    # dataset synthétique
    ds = TMP / "goodset"
    ds.mkdir(parents=True, exist_ok=True)
    rows = [{"messages": [{"role": "user", "content": f"question {i}"},
                          {"role": "assistant", "content": f"answer {i}"}]}
            for i in range(20)]
    (ds / "chatml.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (ds / "metadata.json").write_text(
        json.dumps({"license": "MIT", "source": "unit-test"}), encoding="utf-8")

    hc = dr.health_check(ds)
    assert hc["completeness"] == 1.0 and hc["duplicates"] == 0
    assert hc["quality_score"] >= 80 and hc["decision"] == "accepted", hc

    # dataset pourri → rejeté
    bad = TMP / "badset"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "chatml.jsonl").write_text(
        "\n".join(['{"messages": []}'] * 10), encoding="utf-8")
    hc2 = dr.health_check(bad)
    assert hc2["decision"] == "rejected", hc2

    # memory 100 + gaps 92 sur fichiers temporaires
    dr.DATASET_MEMORY_PATH = TMP / "dataset_memory.json"
    dr.KNOWLEDGE_GAPS_PATH = TMP / "knowledge_gaps.json"
    dr.DATASETS_ROOT = TMP  # register_dataset résout TMP/goodset
    entry = dr.register_dataset("goodset", source="unit-test", license="MIT")
    assert entry["decision"] == "accepted" and entry["usage_count"] == 0
    dr.bump_dataset_usage("goodset")
    mem = json.loads(dr.DATASET_MEMORY_PATH.read_text(encoding="utf-8"))
    assert mem["goodset"]["usage_count"] == 1

    gap = dr.record_knowledge_gap("tâche ratée xyz", 3.2, agent="TestAgent")
    assert gap["status"] == "pending_user_approval"
    gaps = json.loads(dr.KNOWLEDGE_GAPS_PATH.read_text(encoding="utf-8"))
    assert gaps[-1]["score"] == 3.2

    # regression guard 101
    rg = dr.regression_guard(before=0.60, after=0.40)
    assert rg["regression"] and rg["verdict"] == "ROLLBACK"
    rg2 = dr.regression_guard(before=0.60, after=0.62)
    assert not rg2["regression"] and rg2["verdict"] == "KEEP"


# ── 5. Registry 59 ───────────────────────────────────────────────────────────
def t_registry():
    from forge_agents.forge_system_registry import SystemNode
    n = SystemNode(id="x", type="agent")
    assert n.cache_semantic and n.cache_ttl_days == 30
    assert n.max_tokens_budget == 0 and n.provider_fallback == []
    n2 = SystemNode(id="y", type="agent", provider_preferred="mimo",
                    max_cost_day=0.5, latency_p95_ms=2000,
                    concurrency_group="write_reports")
    assert n2.provider_preferred == "mimo" and n2.latency_p95_ms == 2000


# ── 6. Hook forge_call : zero-redundancy réel (stub LLM) ─────────────────────
def t_forge_call_gate():
    import forge_agents.forge_llm as fl
    from forge_agents.token_tracker import get_tracker

    # budget cervelet sain pour le test
    from forge_agents.cervelet import get_cervelet
    get_cervelet().ame.budget_restant = max(get_cervelet().ame.budget_restant, 50.0)

    calls = {"n": 0}

    def stub_claude_cli(prompt, system, model, max_tokens, node="forge_llm",
                        task_type="", tier_label=""):
        calls["n"] += 1
        return "STUB_RESULT_AAOS"

    real = fl._call_claude_cli
    fl._call_claude_cli = stub_claude_cli
    try:
        prompt = f"unique aaos gate test {time.time()}"
        tracker = get_tracker()
        avoided_before = tracker.calls_avoided
        r1 = fl.forge_call(prompt, tier=fl.LLMTier.HAIKU, show_tokens=False,
                           use_openviking=False, nano_mode=False)
        r2 = fl.forge_call(prompt, tier=fl.LLMTier.HAIKU, show_tokens=False,
                           use_openviking=False, nano_mode=False)
        assert r1 == "STUB_RESULT_AAOS" and r2 == "STUB_RESULT_AAOS"
        assert calls["n"] == 1, f"LLM appelé {calls['n']} fois (attendu 1 — zero-redundancy)"
        assert tracker.calls_avoided == avoided_before + 1
    finally:
        fl._call_claude_cli = real


if __name__ == "__main__":
    shutil.rmtree(TMP, ignore_errors=True)
    try:
        check("syntax: 7 fichiers compilent", t_syntax)
        check("fingerprint 63/64/65/78/79/87", t_fingerprint)
        check("token savings 84", t_savings)
        check("dataset quality 92/94/95/96/100/101", t_dataset_quality)
        check("registry 59", t_registry)
        check("forge_call zero-redundancy gate (integration)", t_forge_call_gate)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\nAAOS WAVE: {len(passed)}/6 checks OK")
