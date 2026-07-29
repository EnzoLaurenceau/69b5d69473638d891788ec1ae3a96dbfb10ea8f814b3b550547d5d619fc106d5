#!/usr/bin/env python3
"""Final test: Haiku vs Forge - GitHub Issue Triage"""
import json
import time
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

prompt_path = Path("test_triage.txt")
prompt = prompt_path.read_text()

print("=" * 66)
print("  FINAL TEST: GitHub Issue Triage (Haiku vs Forge)")
print("=" * 66)
print()

results = {}

# TEST 1: HAIKU
print("TEST 1: HAIKU (Direct API)")
print("-" * 66)

try:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    start = time.time()

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    elapsed = (time.time() - start) * 1000  # ms

    results["haiku"] = {
        "status": "OK",
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "total_tokens": message.usage.input_tokens + message.usage.output_tokens,
        "latency_ms": round(elapsed, 0),
        "cost_usd": round((message.usage.input_tokens * 0.000080 + message.usage.output_tokens * 0.000240) / 1000, 5),
    }

    print("Status:        SUCCESS")
    print("Input:         {} tokens".format(results['haiku']['input_tokens']))
    print("Output:        {} tokens".format(results['haiku']['output_tokens']))
    print("Total:         {} tokens".format(results['haiku']['total_tokens']))
    print("Latency:       {:.0f} ms".format(results['haiku']['latency_ms']))
    print("Cost (est):    ${:.5f}".format(results['haiku']['cost_usd']))
    print()
    print("Output preview:")
    print(message.content[0].text[:400])

except Exception as e:
    print("FAILED: {}".format(e))
    results["haiku"] = {"status": "FAILED", "error": str(e)}

print()
print()

# TEST 2: FORGE
print("TEST 2: FORGE (Full Stack)")
print("-" * 66)

try:
    from forge_agents.forge_llm import forge_call, LLMTier

    start = time.time()

    result = forge_call(
        prompt,
        tier=LLMTier.HAIKU,
        task_type="fast_extraction"
    )

    elapsed = (time.time() - start) * 1000  # ms

    results["forge"] = {
        "status": "OK",
        "latency_ms": round(elapsed, 0),
        "output_preview": result[:400],
        "note": "Token counts depend on Forge config + FREE tier routing"
    }

    print("Status:        SUCCESS")
    print("Latency:       {:.0f} ms".format(results['forge']['latency_ms']))
    print("Tier:          FREE (routed to Groq/OpenRouter/etc)")
    print()
    print("Output preview:")
    print(result[:400])

except ImportError as e:
    print("FORGE NOT AVAILABLE (import failed)")
    print("Error: {}".format(e))
    results["forge"] = {
        "status": "NOT_AVAILABLE",
        "error": "forge_agents not available",
        "note": "Set up GROQ_API_KEY, OPENROUTER_API_KEY, or Anthropic fallback"
    }
except Exception as e:
    print("FORGE FAILED: {}".format(e))
    results["forge"] = {
        "status": "FAILED",
        "error": str(e),
        "note": "Check .env API keys"
    }

print()
print()

# SUMMARY TABLE
print("=" * 66)
print("  COMPARISON SUMMARY")
print("=" * 66)
print()

print("Metric                 | Haiku              | Forge")
print("-" * 66)

# Status
print("Status                 | {:<18} | {}".format(
    results['haiku'].get('status', '?'),
    results['forge'].get('status', '?')
))

# Tokens
if "total_tokens" in results["haiku"]:
    h_tokens = results["haiku"]["total_tokens"]
    f_tokens = results["forge"].get("total_tokens", "?")
    if f_tokens != "?":
        diff_pct = round((f_tokens - h_tokens) / h_tokens * 100, 1)
        print("Total tokens           | {:<18} | {} ({:+.1f}%)".format(h_tokens, f_tokens, diff_pct))
    else:
        print("Total tokens           | {:<18} | {} (setup needed)".format(h_tokens, f_tokens))

# Latency
if "latency_ms" in results["haiku"] and "latency_ms" in results["forge"]:
    h_lat = results["haiku"]["latency_ms"]
    f_lat = results["forge"]["latency_ms"]
    ratio = round(f_lat / h_lat, 1) if h_lat else "?"
    print("Latency (ms)           | {:<18} | {} ({}x)".format(h_lat, f_lat, ratio))

# Cost
if "cost_usd" in results["haiku"]:
    print("Cost (USD)             | ${:<17} | $?".format(results['haiku']['cost_usd']))

print()
print()

# KEY FINDINGS
print("KEY FINDINGS:")
print()

if "total_tokens" in results["haiku"]:
    total = results["haiku"]["total_tokens"]
    pct = round(total / 10000 * 100, 1)
    print("1. Haiku used {} tokens for this triage task".format(total))
    print("   Budget: 10,000 tokens | Used: {} ({}%)".format(total, pct))
    print()

if results["forge"]["status"] == "OK":
    print("2. Forge completed successfully")
    print("   Latency: {} ms (vs Haiku {} ms)".format(
        results['forge']['latency_ms'],
        results['haiku'].get('latency_ms', '?')
    ))
else:
    print("2. Forge not ready: {}".format(results['forge'].get('error', 'unknown error')))
    print("   Required: Set up GROQ_API_KEY + OPENROUTER_API_KEY in .env")

print()

# Save results
with open("test_results_FINAL.json", "w") as f:
    json.dump(results, f, indent=2)

print("OK - Results saved: test_results_FINAL.json")
