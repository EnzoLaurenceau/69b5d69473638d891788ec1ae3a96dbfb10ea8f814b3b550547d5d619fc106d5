import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from forge_agents.dataset_rag import get_dataset_rag

rag = get_dataset_rag()

print("=== TEST 1: Coding query ===")
ctx = rag.retrieve_for_context("build a FastAPI REST API with PostgreSQL authentication", top_k=3)
print(ctx[:800] if ctx else "(no results)")

print()
print("=== TEST 2: Metacognition query ===")
ctx2 = rag.retrieve_for_context("analyze problem carefully identify hidden assumptions", top_k=2)
print(ctx2[:600] if ctx2 else "(no results)")

print()
print("=== STATS ===")
stats = rag.stats()
print(f"Categories: {stats['categories']}")
print(f"Examples indexed: {stats['total_examples_indexed']}")
print(f"Rows covered: {stats['total_rows_covered']}")
print(f"Sources: {stats['sources']}")
print(f"Index time: {stats['index_time_s']:.1f}s")
for c in stats.get("top_categories", [])[:5]:
    print(f"  {c['name']}: {c['total']} rows ({c['examples']} sampled)")
