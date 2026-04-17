"""Minimal test: Embedding GPU + Reranker CPU in one process."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Patch FIRST
import torch
if not hasattr(torch, "distributed"):
    class _D: pass
    torch.distributed = _D()
if not hasattr(torch.distributed, "is_initialized"):
    torch.distributed.is_initialized = lambda: False
if not hasattr(torch.distributed, "get_rank"):
    torch.distributed.get_rank = lambda: 0

print("1. Patch done", flush=True)

import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mneme.config import load_config, SearchConfig
from mneme.embeddings import get_provider
from mneme.store import Store

config = load_config()

print("2. Loading embedding on GPU...", flush=True)
provider = get_provider(config.embedding)
provider.warmup()
print("3. Embedding ready", flush=True)

store = Store(config.db_path, provider.dimension())

print("4. Testing one embed...", flush=True)
vec = provider.embed(["Test query"])
print(f"5. Embed OK, dim={len(vec[0])}", flush=True)

# Force CUDA sync before loading second model
torch.cuda.synchronize()
print("6. CUDA synced", flush=True)

print("7. Loading reranker on CPU...", flush=True)
from sentence_transformers import CrossEncoder
reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cpu")
print("8. Reranker loaded", flush=True)

print("9. Warmup predict...", flush=True)
s = reranker.predict([("warmup", "warmup")], show_progress_bar=False)
print(f"10. Warmup OK: {s[0]:.4f}", flush=True)

print("11. Now: embed + rerank in sequence...", flush=True)
vec2 = provider.embed(["Was ist Mneme?"])
torch.cuda.synchronize()
print("12. Embed done, now predict...", flush=True)
scores = reranker.predict([
    ("Was ist Mneme?", "Mneme ist ein lokaler MCP-Server"),
    ("Was ist Mneme?", "Trading Strategie fuer Anfaenger"),
], show_progress_bar=False)
print(f"13. Scores: {scores[0]:.4f}, {scores[1]:.4f}", flush=True)

store.close()
print("SUCCESS", flush=True)
