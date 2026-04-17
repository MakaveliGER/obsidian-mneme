"""Debug: Where EXACTLY does search+rerank hang?"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch
if not hasattr(torch, "distributed"):
    class _D: pass
    torch.distributed = _D()
if not hasattr(torch.distributed, "is_initialized"):
    torch.distributed.is_initialized = lambda: False
if not hasattr(torch.distributed, "get_rank"):
    torch.distributed.get_rank = lambda: 0

import os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mneme.config import load_config, SearchConfig
from mneme.embeddings import get_provider
from mneme.store import Store

config = load_config()

print("1. Loading embedding on GPU...", flush=True)
provider = get_provider(config.embedding)
provider.warmup()
print("2. Embedding ready", flush=True)

store = Store(config.db_path, provider.dimension())

# Simulate Run A: do 5 embeds (like the eval does)
print("3. Simulating Run A (5 queries without reranker)...", flush=True)
for i in range(5):
    vec = provider.embed([f"Test query {i}"])
    results = store.vector_search(vec[0], top_k=10)
    print(f"   [{i+1}/5] OK ({len(results)} results)", flush=True)

print("4. Run A done. Loading reranker on CPU...", flush=True)
from sentence_transformers import CrossEncoder
reranker_model = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cpu")
reranker_model.predict([("warmup", "warmup")], show_progress_bar=False)
print("5. Reranker loaded + warmup done", flush=True)

# Now simulate Run B: embed + rerank
query = "Was ist Mneme?"
print(f"6. Embed query: '{query}'...", flush=True)
t0 = time.monotonic()
embedding = provider.embed([query])[0]
print(f"7. Embed done ({(time.monotonic()-t0)*1000:.0f}ms)", flush=True)

print("8. Vector search...", flush=True)
vec_results = store.vector_search(embedding, top_k=30)
print(f"9. Got {len(vec_results)} vector results", flush=True)

print("10. BM25 search...", flush=True)
bm25_results = store.bm25_search(query, top_k=20)
print(f"11. Got {len(bm25_results)} BM25 results", flush=True)

print("12. torch.cuda.synchronize()...", flush=True)
t0 = time.monotonic()
torch.cuda.synchronize()
print(f"13. Synced ({(time.monotonic()-t0)*1000:.0f}ms)", flush=True)

# Build pairs
all_results = vec_results + bm25_results
pairs = [(query, r.content[:200]) for r in all_results[:20]]
print(f"14. Predict {len(pairs)} pairs on CPU...", flush=True)
t0 = time.monotonic()
scores = reranker_model.predict(pairs, show_progress_bar=False)
print(f"15. Predict done ({(time.monotonic()-t0)*1000:.0f}ms), scores[0]={scores[0]:.4f}", flush=True)

store.close()
print("SUCCESS", flush=True)
