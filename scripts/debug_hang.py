"""DEFINITIVE debug: exact step where search+rerank hangs."""
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
from mneme.search import rrf_fusion

config = load_config()
provider = get_provider(config.embedding)
provider.warmup()
store = Store(config.db_path, provider.dimension())
print("Embedding ready", flush=True)

# Simulate Run A
print("Run A: 3 queries...", flush=True)
for i in range(3):
    e = provider.embed([f"Query {i}"])[0]
    store.vector_search(e, top_k=10)
    print(f"  A[{i+1}] OK", flush=True)

# Load reranker
print("Loading CrossEncoder on CPU...", flush=True)
from sentence_transformers import CrossEncoder
reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cpu")
reranker.predict([("w","w")], show_progress_bar=False)
print("Reranker ready", flush=True)

# Now the EXACT sequence from search()
query = "Was ist Mneme?"

print("STEP 1: embed...", flush=True)
embedding = provider.embed([query])[0]
print(f"STEP 2: embed done ({len(embedding)} dims)", flush=True)

print("STEP 3: vector_search...", flush=True)
vec = store.vector_search(embedding, top_k=30)
print(f"STEP 4: {len(vec)} vec results", flush=True)

print("STEP 5: bm25_search...", flush=True)
bm25 = store.bm25_search(query, top_k=20)
print(f"STEP 6: {len(bm25)} bm25 results", flush=True)

print("STEP 7: rrf_fusion...", flush=True)
fused = rrf_fusion([vec, bm25], weights=[0.6, 0.4])
print(f"STEP 8: {len(fused)} fused", flush=True)

print("STEP 9: cuda sync...", flush=True)
torch.cuda.synchronize()
print("STEP 10: synced", flush=True)

# Rerank ONE AT A TIME with progress
candidates = fused[:10]
print(f"STEP 11: rerank {len(candidates)} candidates one by one...", flush=True)
for i, r in enumerate(candidates):
    text = r.content[:500]
    print(f"  [{i+1}/{len(candidates)}] predicting...", end="", flush=True)
    t0 = time.monotonic()
    s = reranker.predict([(query, text)], show_progress_bar=False)[0]
    ms = (time.monotonic() - t0) * 1000
    print(f" score={s:.4f} ({ms:.0f}ms)", flush=True)

store.close()
print("SUCCESS", flush=True)
