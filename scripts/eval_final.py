"""Eval — alles inline, kein Reranker-Klasse, kein SearchEngine. Direkte Calls."""
import sys, os, time, math, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch
if not hasattr(torch, "distributed"):
    class _D: pass
    torch.distributed = _D()
if not hasattr(torch.distributed, "is_initialized"):
    torch.distributed.is_initialized = lambda: False
if not hasattr(torch.distributed, "get_rank"):
    torch.distributed.get_rank = lambda: 0

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path
from mneme.config import load_config
from mneme.embeddings import get_provider
from mneme.store import Store
from mneme.search import rrf_fusion

config = load_config()
golden = json.loads(Path(os.path.join(os.path.dirname(__file__), "..", "tests", "golden_dataset.json")).read_text(encoding="utf-8"))
print(f"{len(golden)} questions", flush=True)

# Load embedding on GPU
provider = get_provider(config.embedding)
provider.warmup()
store = Store(config.db_path, provider.dimension())
print("Embedding on GPU ready", flush=True)

# Load reranker on GPU (single predict works, batch hangs)
from sentence_transformers import CrossEncoder
reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda")
reranker.predict([("warmup", "warmup")], show_progress_bar=False)
print("Reranker on GPU ready", flush=True)

def normalize(p):
    return p.replace("\\", "/").lower().removesuffix(".md")

def paths_match(expected, retrieved):
    e, r = normalize(expected), normalize(retrieved)
    return e in r or r in e

def search_and_rerank(query, top_k=10, use_reranker=False, use_gars=False, gw=0.3):
    # Embed
    embedding = provider.embed([query])[0]
    torch.cuda.synchronize()

    # Retrieve
    vec = store.vector_search(embedding, top_k=top_k * 3)
    bm25 = store.bm25_search(query, top_k=top_k * 2)
    fused = rrf_fusion([vec, bm25], weights=[0.6, 0.4])

    if use_reranker:
        torch.cuda.synchronize()
        candidates = fused[:top_k * 3]
        scored = []
        for r in candidates:
            text = r.content[:2000]
            s = float(reranker.predict([(query, text)], show_progress_bar=False)[0])
            sig = 1.0 / (1.0 + math.exp(-s))
            if sig >= 0.2:
                from mneme.store import SearchResult
                scored.append(SearchResult(
                    chunk_id=r.chunk_id, note_path=r.note_path,
                    note_title=r.note_title, heading_path=r.heading_path,
                    content=r.content, score=sig, tags=r.tags,
                ))
        scored.sort(key=lambda x: x.score, reverse=True)
        results = scored[:top_k]
    else:
        results = fused[:top_k]

    if use_gars:
        centrality = store.get_centrality_map()
        final = []
        for r in results:
            c = centrality.get(r.note_path, 0.0)
            from mneme.store import SearchResult
            final.append(SearchResult(
                chunk_id=r.chunk_id, note_path=r.note_path,
                note_title=r.note_title, heading_path=r.heading_path,
                content=r.content, score=(1-gw)*r.score + gw*c, tags=r.tags,
            ))
        final.sort(key=lambda x: x.score, reverse=True)
        return final

    return results

def run_eval(label, use_reranker=False, use_gars=False):
    print(f"\n=== {label} ===", flush=True)
    hits1 = hits3 = hits10 = 0
    mrr_sum = 0.0
    t0 = time.monotonic()
    for i, entry in enumerate(golden):
        q = entry["question"]
        expected = entry["expected_contexts"]
        results = search_and_rerank(q, top_k=10, use_reranker=use_reranker, use_gars=use_gars)
        paths = [r.note_path for r in results]

        h1 = any(paths_match(e, p) for e in expected for p in paths[:1])
        h3 = any(paths_match(e, p) for e in expected for p in paths[:3])
        h10 = any(paths_match(e, p) for e in expected for p in paths[:10])
        mrr = 0.0
        for rank, p in enumerate(paths, 1):
            if any(paths_match(e, p) for e in expected):
                mrr = 1.0 / rank
                break

        hits1 += h1; hits3 += h3; hits10 += h10; mrr_sum += mrr
        sym = "@1" if h1 else "@3" if h3 else "@10" if h10 else "MISS"
        print(f"  [{i+1}/{len(golden)}] {sym} {q[:50]}", flush=True)

    n = len(golden)
    elapsed = time.monotonic() - t0
    h1r, h3r, h10r, mmrr = hits1/n, hits3/n, hits10/n, mrr_sum/n
    print(f"  => Hit@1={h1r:.1%}  Hit@3={h3r:.1%}  Hit@10={h10r:.1%}  MRR={mmrr:.4f}  ({elapsed:.1f}s)", flush=True)
    return (label, h1r, h3r, h10r, mmrr)

# Run all configs
results = []
results.append(run_eval("A: Baseline", use_reranker=False, use_gars=False))
results.append(run_eval("B: + Reranking", use_reranker=True, use_gars=False))
results.append(run_eval("C: + Reranking + GARS", use_reranker=True, use_gars=True))

store.close()

print(f"\n{'='*70}", flush=True)
print("ERGEBNIS", flush=True)
print(f"{'='*70}", flush=True)
print(f"{'Config':<30} {'Hit@1':<8} {'Hit@3':<8} {'Hit@10':<8} {'MRR':<8}", flush=True)
print("-" * 70, flush=True)
for label, h1, h3, h10, mrr in results:
    print(f"{label:<30} {h1:<8.1%} {h3:<8.1%} {h10:<8.1%} {mrr:<8.4f}", flush=True)
best = max(results, key=lambda x: x[4])
print(f"\nBest: {best[0]} (MRR={best[4]:.4f})", flush=True)
print("DONE", flush=True)
