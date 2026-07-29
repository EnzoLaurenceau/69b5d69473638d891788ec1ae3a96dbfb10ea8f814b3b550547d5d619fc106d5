#!/usr/bin/env python3
"""
Test Forge avec métriques
"""
import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "00_CORE"))

# Import Forge components
try:
    from forge_agents.forge_llm import forge_call, LLMTier
    from forge_agents.token_tracker import get_tracker
except ImportError as e:
    print(f"❌ Import failed: {e}")
    print("   forge_agents not available")
    sys.exit(1)

# Read prompt
prompt_file = Path(__file__).parent / "test_triage.txt"
prompt = prompt_file.read_text()

print("🟣 TEST 2: FORGE (Full Stack)")
print("─" * 65)

tracker = get_tracker()
start = time.time()

try:
    # Call via Forge LLM router (should use HAIKU tier)
    result = forge_call(
        prompt,
        tier=LLMTier.HAIKU,
        task_type="fast_extraction"
    )

    elapsed = (time.time() - start) * 1000  # ms

    # Try to get token counts from tracker
    stats = tracker.get_stats()

    print(f"✅ Status:        SUCCESS")
    print(f"📥 Input tokens:  {stats.get('input_tokens', '?')}")
    print(f"📤 Output tokens: {stats.get('output_tokens', '?')}")
    print(f"📊 Total:         {stats.get('total_tokens', '?')} tokens")
    print(f"⏱️  Latency:       {elapsed:.0f} ms")
    print(f"💰 Cost:          ${stats.get('cost', '?')}")
    print("")
    print("Output preview:")
    print(result[:400])

    # Save metrics
    metrics = {
        "status": "success",
        "input": stats.get('input_tokens'),
        "output": stats.get('output_tokens'),
        "total": stats.get('total_tokens'),
        "latency": elapsed,
        "cost": stats.get('cost')
    }

except Exception as e:
    print(f"⚠️  FORGE NOT READY: {e}")
    print(f"   (Setup may be needed)")
    metrics = {"status": "failed", "error": str(e), "latency": elapsed}

# Save for comparison
with open(Path(__file__).parent / "test_forge_result.json", "w") as f:
    json.dump(metrics, f, indent=2)

print("\n✅ Forge test complete")
