"""
Test script for RAG enrichment and tool call optimization.
"""

import sys
sys.path.insert(0, '00_CORE')

def test_multi_source_brain():
    """Test the multi-source brain orchestrator."""
    print("=" * 60)
    print("TEST: MultiSourceBrainOrchestrator")
    print("=" * 60)
    
    from forge_agents.multi_source_brain import (
        get_brain, classify_scale, ScaleClass, nmp_data_need
    )
    
    # Test scale classification
    test_cases = [
        (500_000, ScaleClass.FEATHERWEIGHT),
        (5_000_000, ScaleClass.LIGHTWEIGHT),
        (50_000_000, ScaleClass.MIDWEIGHT),
        (500_000_000, ScaleClass.HEAVYWEIGHT),
        (1_500_000_000, ScaleClass.MASSIVE),
    ]
    
    print("\n1. Scale Classification:")
    for size, expected in test_cases:
        result = classify_scale(size)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {size:>12,} bytes → {result.value} (expected {expected.value})")
    
    # Test NMP message generation
    print("\n2. NMP Message Generation:")
    msg = nmp_data_need("RECON", ["huggingface", "github_gists", "kaggle"], 
                        ScaleClass.LIGHTWEIGHT, 5_000_000, "vulnerability detection")
    print(f"  DATA_NEED: {msg}")
    
    # Test brain initialization
    print("\n3. Brain Initialization:")
    brain = get_brain()
    print(f"  ✅ Brain created: {type(brain).__name__}")
    print(f"  ✅ DL root: {brain.dl_root}")
    
    # Test data need detection
    print("\n4. Data Need Detection:")
    from forge_agents.agent_nodes import _needs_external_data
    test_tasks = [
        "Find dataset for training vulnerability detection model",
        "Analyze this code for SQL injection",
        "Download HuggingFace dataset for fine-tuning",
        "Simple format conversion task"
    ]
    for task in test_tasks:
        needs, est_bytes = _needs_external_data(task)
        status = "✅" if needs else "❌"
        print(f"  {status} '{task[:50]}...' → needs_data={needs}, est={est_bytes:,} bytes")
    


def test_tool_batcher():
    """Test the tool call batcher."""
    print("\n" + "=" * 60)
    print("TEST: ToolCallBatcher")
    print("=" * 60)
    
    from forge_agents.tool_batcher import get_batcher, reset_batcher
    
    # Reset batcher
    reset_batcher()
    batcher = get_batcher(batch_size=5)
    
    print("\n1. Initial Stats:")
    stats = batcher.stats()
    print(f"  ✅ Batcher created with batch_size=5")
    print(f"  ✅ Stats: {stats}")
    
    # Test queuing calls
    print("\n2. Queuing Tool Calls:")
    for i in range(12):
        batcher.queue("read_file", {"path": f"/path/to/file_{i}.py"})
    print(f"  ✅ Queued 12 calls")
    print(f"  ✅ Pending: {batcher.pending_count()}")
    
    # Test flush
    print("\n3. Flushing Batches:")
    results = batcher.flush_all()
    print(f"  ✅ Flushed all calls")
    print(f"  ✅ Results: {len(results)} items")
    print(f"  ✅ Final stats: {batcher.stats()}")
    
    # Test grouping by tool
    print("\n4. Tool Grouping:")
    reset_batcher()
    batcher = get_batcher(batch_size=3, group_by_tool=True)
    
    batcher.queue("read_file", {"path": "/a.py"})
    batcher.queue("read_file", {"path": "/b.py"})
    batcher.queue("search_files", {"pattern": "test"})
    batcher.queue("read_file", {"path": "/c.py"})
    batcher.queue("search_files", {"pattern": "foo"})
    
    print(f"  ✅ Queued mixed calls")
    results = batcher.flush_all()
    print(f"  ✅ Flushed: {len(results)} results")
    print(f"  ✅ Stats: {batcher.stats()}")
    


def test_adaptive_rag():
    """Test the adaptive RAG system."""
    print("\n" + "=" * 60)
    print("TEST: Adaptive RAG")
    print("=" * 60)
    
    from forge_agents.adaptive_rag import classify_strategy, STRATEGY_PARAMS
    
    # Test strategy classification
    print("\n1. Strategy Classification:")
    test_cases = [
        ("Format this code nicely", "formatter", 2, "NONE"),
        ("Résume ce document", "summarizer", 2, "LIGHT"),
        ("Analyze vulnerability in login endpoint", "security_agent", 2, "STANDARD"),
        ("Build market scan for competitor analysis", "market_agent", 2, "FULL"),
        ("Simple rename task", "helper", 1, "FULL"),  # cycle 1 = FULL
        ("Complex architecture design", "orch", 3, "FULL"),  # orchestrator = FULL
    ]
    
    for task, agent, cycle, expected in test_cases:
        result = classify_strategy(task, agent, cycle)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{task[:40]}...' → {result} (expected {expected})")
    
    # Test strategy parameters
    print("\n2. Strategy Parameters:")
    for strategy, params in STRATEGY_PARAMS.items():
        print(f"  {strategy}: top_k={params['top_k']}, viking={params['max_chars_viking']}, "
              f"findings={params['max_chars_findings']}, graphify={params['use_graphify']}")
    


def test_zsl_integration():
    """Test ZSL integration with the graph."""
    print("\n" + "=" * 60)
    print("TEST: ZSL Integration")
    print("=" * 60)
    
    from forge_agents.zsl_cyber import ZSLCyberEngine
    
    engine = ZSLCyberEngine()
    
    # Test code analysis
    print("\n1. Code Analysis:")
    code = """
    user_id = request.GET.get('id')
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    """
    result = engine.analyze_code(code)
    print(f"  ✅ Confidence: {result.confidence:.1%}")
    print(f"  ✅ Findings: {len(result.findings)}")
    for f in result.findings:
        print(f"    - {f['type']}: {f['description']}")
    
    # Test CTF analysis
    print("\n2. CTF Analysis:")
    result = engine.analyze_ctf_challenge(
        "Binary exploitation challenge with buffer overflow vulnerability",
        hints=["rop chain", "shellcode"]
    )
    print(f"  ✅ Confidence: {result.confidence:.1%}")
    print(f"  ✅ Categories: {len(result.findings)}")
    for f in result.findings:
        print(f"    - {f['category']}: {f['confidence']:.1%}")
    
    # Test threat intel
    print("\n3. Threat Intelligence:")
    result = engine.analyze_threat_intel(
        "APT28 group using zero-day exploit CVE-2024-1234. "
        "C2 server at 192.168.1.100. Malware hash: a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    )
    print(f"  ✅ Confidence: {result.confidence:.1%}")
    print(f"  ✅ Findings: {len(result.findings)}")
    for f in result.findings:
        print(f"    - {f['type']}: {f.get('count', 0)} items")
    


def test_graph_compilation():
    """Test that the graph compiles with all new nodes."""
    print("\n" + "=" * 60)
    print("TEST: Graph Compilation")
    print("=" * 60)
    
    from forge_agents.forge_graph import build_forge_graph
    
    # Pas de try/except ici : une exception DOIT faire échouer le test. La version
    # précédente l'attrapait et renvoyait False — or pytest ignore la valeur de retour,
    # donc une compilation de graphe cassée passait au vert. Test à signal nul.
    graph = build_forge_graph(use_sqlite=False)
    nodes = list(graph.nodes.keys())
    print(f"\nGraph compiled — nodes ({len(nodes)}): {', '.join(nodes)}")

    expected_nodes = ['zsl_analysis', 'neuro_symbolic_verification', 'anti_hallucination']
    missing = [n for n in expected_nodes if n not in nodes]
    for node in expected_nodes:
        print(f"  {'OK     ' if node in nodes else 'MISSING'} {node}")

    assert not missing, f"nœuds absents du graphe compilé : {missing}"


if __name__ == "__main__":
    print("FORGE SYSTEM TESTS")
    print("=" * 60)
    
    tests = [
        ("MultiSourceBrain", test_multi_source_brain),
        ("ToolCallBatcher", test_tool_batcher),
        ("AdaptiveRAG", test_adaptive_rag),
        ("ZSL Integration", test_zsl_integration),
        ("Graph Compilation", test_graph_compilation),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            result = test_fn()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name} FAILED: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    all_passed = all(r for _, r in results)
    print(f"\n{'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
