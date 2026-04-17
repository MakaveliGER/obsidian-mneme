"""Eval comparison — runs 4 configurations and compares Hit Rate + MRR."""

import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Patch torch.distributed BEFORE any imports
import torch
if not hasattr(torch, "distributed"):
    class _D: pass
    torch.distributed = _D()
if not hasattr(torch.distributed, "is_initialized"):
    torch.distributed.is_initialized = lambda: False
if not hasattr(torch.distributed, "get_rank"):
    torch.distributed.get_rank = lambda: 0

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import time
from pathlib import Path
from mneme.config import load_config, SearchConfig, ScoringConfig
from mneme.embeddings import get_provider
from mneme.reranker import Reranker
from mneme.search import SearchEngine
from mneme.store import Store
from mneme.eval import load_golden_dataset, evaluate_retrieval


def main():
    config = load_config()
    golden = load_golden_dataset(Path(os.path.join(os.path.dirname(__file__), "..", "tests", "golden_dataset.json")))
    print(f"Loaded {len(golden)} questions", flush=True)

    # Load embedding model
    print("Loading embedding model...", flush=True)
    t0 = time.monotonic()
    provider = get_provider(config.embedding)
    provider.warmup()
    print(f"Embedding ready ({time.monotonic() - t0:.1f}s)", flush=True)

    store = Store(config.db_path, provider.dimension())
    results = []

    # --- Run A: Baseline ---
    print("\n=== Run A: Baseline (RRF 60/40, no rerank, no GARS) ===", flush=True)
    cfg = SearchConfig(vector_weight=0.6, bm25_weight=0.4, top_k=10)
    engine = SearchEngine(store=store, embedding_provider=provider, config=cfg)
    t0 = time.monotonic()
    ra = evaluate_retrieval(engine, golden, top_k=10)
    print(f"  Hit@1={ra.hit_rate_at_1:.1%}  Hit@3={ra.hit_rate_at_3:.1%}  Hit@10={ra.hit_rate_at_10:.1%}  MRR={ra.mean_mrr:.4f}  ({time.monotonic()-t0:.1f}s)", flush=True)
    results.append(("A: Baseline", ra))

    # --- Load Reranker ---
    print("\nLoading reranker...", flush=True)
    t0 = time.monotonic()
    reranker = Reranker(model_name="BAAI/bge-reranker-v2-m3", threshold=0.2)
    reranker.warmup()
    print(f"Reranker ready ({time.monotonic() - t0:.1f}s)", flush=True)

    # --- Run B: + Reranking ---
    print("\n=== Run B: + Reranking (threshold=0.2) ===", flush=True)
    engine_b = SearchEngine(store=store, embedding_provider=provider, config=cfg, reranker=reranker)
    t0 = time.monotonic()
    rb = evaluate_retrieval(engine_b, golden, top_k=10)
    print(f"  Hit@1={rb.hit_rate_at_1:.1%}  Hit@3={rb.hit_rate_at_3:.1%}  Hit@10={rb.hit_rate_at_10:.1%}  MRR={rb.mean_mrr:.4f}  ({time.monotonic()-t0:.1f}s)", flush=True)
    results.append(("B: + Reranking", rb))

    # --- Run C: + Reranking + GARS ---
    print("\n=== Run C: + Reranking + GARS (weight=0.3) ===", flush=True)
    scoring = ScoringConfig(gars_enabled=True, graph_weight=0.3)
    engine_c = SearchEngine(store=store, embedding_provider=provider, config=cfg, reranker=reranker, scoring_config=scoring)
    t0 = time.monotonic()
    rc = evaluate_retrieval(engine_c, golden, top_k=10)
    print(f"  Hit@1={rc.hit_rate_at_1:.1%}  Hit@3={rc.hit_rate_at_3:.1%}  Hit@10={rc.hit_rate_at_10:.1%}  MRR={rc.mean_mrr:.4f}  ({time.monotonic()-t0:.1f}s)", flush=True)
    results.append(("C: + Rerank + GARS", rc))

    # --- Run D: + Reranking + GARS + Query Expansion ---
    print("\n=== Run D: + Reranking + GARS + Query Expansion ===", flush=True)
    cfg_qe = SearchConfig(vector_weight=0.6, bm25_weight=0.4, top_k=10, query_expansion=True)
    engine_d = SearchEngine(store=store, embedding_provider=provider, config=cfg_qe, reranker=reranker, scoring_config=scoring)
    t0 = time.monotonic()
    rd = evaluate_retrieval(engine_d, golden, top_k=10)
    print(f"  Hit@1={rd.hit_rate_at_1:.1%}  Hit@3={rd.hit_rate_at_3:.1%}  Hit@10={rd.hit_rate_at_10:.1%}  MRR={rd.mean_mrr:.4f}  ({time.monotonic()-t0:.1f}s)", flush=True)
    results.append(("D: + QE", rd))

    store.close()

    # --- Summary ---
    print(f"\n{'='*70}", flush=True)
    print("COMPARISON SUMMARY", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"{'Config':<30} {'Hit@1':<8} {'Hit@3':<8} {'Hit@10':<8} {'MRR':<8}", flush=True)
    print("-" * 70, flush=True)
    for label, r in results:
        print(f"{label:<30} {r.hit_rate_at_1:<8.1%} {r.hit_rate_at_3:<8.1%} {r.hit_rate_at_10:<8.1%} {r.mean_mrr:<8.4f}", flush=True)

    best = max(results, key=lambda x: x[1].mean_mrr)
    print(f"\nBest config: {best[0]} (MRR={best[1].mean_mrr:.4f})", flush=True)


if __name__ == "__main__":
    main()
