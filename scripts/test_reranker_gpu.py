"""Minimal test: Does the CrossEncoder reranker work on GPU?"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch
print(f"1. torch loaded, version={torch.__version__}", flush=True)

# Patch torch.distributed
if not hasattr(torch, "distributed"):
    class _D: pass
    torch.distributed = _D()
if not hasattr(torch.distributed, "is_initialized"):
    torch.distributed.is_initialized = lambda: False
if not hasattr(torch.distributed, "get_rank"):
    torch.distributed.get_rank = lambda: 0
print("2. torch.distributed patched", flush=True)

# Test GPU
print(f"3. CUDA available: {torch.cuda.is_available()}", flush=True)
if torch.cuda.is_available():
    print(f"   Device: {torch.cuda.get_device_name(0)}", flush=True)

# Load CrossEncoder
print("4. Loading CrossEncoder on GPU...", flush=True)
from sentence_transformers import CrossEncoder
model = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda")
print("5. CrossEncoder loaded!", flush=True)

# ONE predict call
print("6. Testing predict()...", flush=True)
scores = model.predict(
    [("Was ist Mneme?", "Mneme ist ein lokaler MCP-Server fuer semantische Vault-Suche.")],
    show_progress_bar=False,
)
print(f"7. Score: {scores[0]:.4f}", flush=True)

# Multiple predict
print("8. Testing 10 pairs...", flush=True)
pairs = [(f"Query {i}", f"Document {i} about topic {i}") for i in range(10)]
scores = model.predict(pairs, show_progress_bar=False)
print(f"9. 10 scores done, first={scores[0]:.4f}", flush=True)

print("SUCCESS", flush=True)
