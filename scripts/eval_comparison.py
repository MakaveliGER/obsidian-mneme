"""Eval comparison — runs 4 configurations and compares Hit Rate + MRR."""

import json
import os
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mneme.config import load_config, SearchConfig, RerankingConfig, ScoringConfig
from mneme.embeddings import get_provider
from mneme.eval import load_golden_dataset, evaluate_retrieval, print_report
from mneme.reranker import Reranker
from mneme.search import SearchEngine
from mneme.store import Store


def run_eval(engine, golden, label, top_k=10):
    """Run evaluation and return report."""
    print(f"\n{'='*60}")
    print(f"Config: {label}")
    print(f"{'='*60}")
    t0 = time.monotonic()
    report = evaluate_retrieval(engine, golden, top_k=top_k)
    elapsed = time.monotonic() - t0
    print_report(report)
    print(f"  Eval time: {elapsed:.1f}s")
    return {
        "label": label,
        "hit_at_1": report.hit_rate_at_1,
        "hit_at_3": report.hit_rate_at_3,
        "hit_at_10": report.hit_rate_at_10,
        "mrr": report.mean_mrr,
        "elapsed_s": round(elapsed, 1),
    }


def main():
    config = load_config()
    from pathlib import Path
    dataset_path = Path(os.path.join(os.path.dirname(__file__), "..", "tests", "golden_dataset.json"))
    golden = load_golden_dataset(dataset_path)
    print(f"Loaded {len(golden)} questions")

    # Load model once
    print("Loading embedding model...")
    t0 = time.monotonic()
    provider = get_provider(config.embedding)
    if hasattr(provider, "warmup"):
        provider.warmup()
    print(f"Model loaded in {time.monotonic() - t0:.1f}s")

    store = Store(config.db_path, provider.dimension())
    results = []

    # --- Run A: Baseline (current defaults, no reranking, no GARS) ---
    search_cfg = SearchConfig(vector_weight=0.6, bm25_weight=0.4, top_k=10)
    engine = SearchEngine(store=store, embedding_provider=provider, config=search_cfg)
    results.append(run_eval(engine, golden, "A: Baseline (RRF 60/40, no rerank, no GARS)"))

    # --- Run B: + Reranking ---
    reranker = Reranker(model_name="BAAI/bge-reranker-v2-m3", threshold=0.2)
    print("\nLoading reranker model...")
    t0 = time.monotonic()
    reranker.warmup()
    print(f"Reranker loaded in {time.monotonic() - t0:.1f}s")

    engine_rerank = SearchEngine(
        store=store, embedding_provider=provider, config=search_cfg,
        reranker=reranker,
    )
    results.append(run_eval(engine_rerank, golden, "B: + Reranking (threshold=0.2)"))

    # --- Run C: + Reranking + GARS ---
    scoring_cfg = ScoringConfig(gars_enabled=True, graph_weight=0.3)
    engine_gars = SearchEngine(
        store=store, embedding_provider=provider, config=search_cfg,
        reranker=reranker, scoring_config=scoring_cfg,
    )
    results.append(run_eval(engine_gars, golden, "C: + Reranking + GARS (weight=0.3)"))

    # --- Run D: + Reranking + GARS + Query Expansion ---
    search_cfg_qe = SearchConfig(vector_weight=0.6, bm25_weight=0.4, top_k=10, query_expansion=True)
    engine_qe = SearchEngine(
        store=store, embedding_provider=provider, config=search_cfg_qe,
        reranker=reranker, scoring_config=scoring_cfg,
    )
    results.append(run_eval(engine_qe, golden, "D: + Reranking + GARS + Query Expansion"))

    store.close()

    # --- Summary ---
    print(f"\n{'='*70}")
    print("COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"{'Config':<50} {'Hit@1':<8} {'Hit@3':<8} {'Hit@10':<8} {'MRR':<8}")
    print("-" * 70)
    for r in results:
        h1 = f"{r['hit_at_1']:.0%}"
        h3 = f"{r['hit_at_3']:.0%}"
        h10 = f"{r['hit_at_10']:.0%}"
        mrr = f"{r['mrr']:.3f}"
        print(f"{r['label']:<50} {h1:<8} {h3:<8} {h10:<8} {mrr:<8}")

    # Best config
    best = max(results, key=lambda r: r["mrr"])
    print(f"\nBest config: {best['label']} (MRR={best['mrr']:.3f})")


if __name__ == "__main__":
    main()
