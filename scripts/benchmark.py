"""Mneme GPU Backend Benchmark — measures real performance on the vault."""

import gc
import os
import sys
import time
import statistics

# Fix Windows console encoding for Unicode
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def get_process_memory_mb():
    """Get current process RSS in MB."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def benchmark_embedding_provider(provider, chunks_texts, label):
    """Benchmark an embedding provider on real chunk texts."""
    print(f"\n{'='*60}")
    print(f"Benchmark: {label}")
    print(f"{'='*60}")

    # Warmup
    print("  Warming up model...")
    mem_before = get_process_memory_mb()
    t0 = time.monotonic()
    if hasattr(provider, "warmup"):
        provider.warmup()
    else:
        provider.embed(["warmup text"])
    warmup_time = time.monotonic() - t0
    mem_after_warmup = get_process_memory_mb()
    print(f"  Model loaded in {warmup_time:.1f}s")
    print(f"  RAM: {mem_before:.0f} MB → {mem_after_warmup:.0f} MB (+{mem_after_warmup - mem_before:.0f} MB)")

    # Embedding throughput
    print(f"  Embedding {len(chunks_texts)} chunks...")
    batch_size = 32
    t0 = time.monotonic()
    all_embeddings = []
    for i in range(0, len(chunks_texts), batch_size):
        batch = chunks_texts[i:i + batch_size]
        embs = provider.embed(batch)
        all_embeddings.extend(embs)
    embed_time = time.monotonic() - t0
    throughput = len(chunks_texts) / embed_time
    mem_after_embed = get_process_memory_mb()

    print(f"  Embedded in {embed_time:.1f}s ({throughput:.1f} chunks/s)")
    print(f"  RAM after embedding: {mem_after_embed:.0f} MB")
    print(f"  Dimension: {len(all_embeddings[0])}")

    # Search benchmark (10 queries)
    queries = [
        "KI-Strategie für Unternehmen",
        "RAG Pipeline Architektur",
        "Obsidian Vault Organisation",
        "Python Entwicklung Best Practices",
        "Web3 Blockchain Consulting",
        "Projektmanagement Methoden",
        "Machine Learning Embeddings",
        "Wissensmanagement Tools",
        "Trading Strategie Finanzen",
        "Weiterbildung KI Akademie",
    ]
    search_times = []
    for q in queries:
        t0 = time.monotonic()
        provider.embed([q])
        search_times.append((time.monotonic() - t0) * 1000)  # ms

    avg_search = statistics.mean(search_times)
    print(f"  Search (10 queries avg): {avg_search:.1f}ms")

    return {
        "label": label,
        "warmup_s": round(warmup_time, 1),
        "embed_time_s": round(embed_time, 1),
        "throughput": round(throughput, 1),
        "ram_peak_mb": round(mem_after_embed),
        "search_avg_ms": round(avg_search, 1),
        "dimension": len(all_embeddings[0]),
    }


def main():
    # Load real chunk texts from the vault index
    from mneme.config import load_config
    from mneme.store import Store

    config = load_config()

    # Get chunk texts from DB (no model needed for this)
    import sqlite3
    conn = sqlite3.connect(str(config.db_path))
    rows = conn.execute("SELECT content FROM chunks").fetchall()
    conn.close()
    chunks_texts = [r[0] for r in rows]
    print(f"Loaded {len(chunks_texts)} chunks from vault index")

    results = []

    # --- Backend A: sentence-transformers CPU ---
    try:
        from mneme.embeddings.sentence_transformers import SentenceTransformersProvider
        provider = SentenceTransformersProvider("BAAI/bge-m3")
        r = benchmark_embedding_provider(provider, chunks_texts, "sentence-transformers CPU (PyTorch)")
        results.append(r)
        del provider
        gc.collect()
    except Exception as e:
        print(f"  FAILED: {e}")

    # --- Backend B: ONNX CPU ---
    try:
        from mneme.embeddings.onnx_provider import ONNXProvider
        provider = ONNXProvider("BAAI/bge-m3", backend="cpu")
        r = benchmark_embedding_provider(provider, chunks_texts, "ONNX Runtime CPU")
        results.append(r)
        del provider
        gc.collect()
    except Exception as e:
        print(f"\n  ONNX CPU FAILED: {e}")

    # --- Backend C: ONNX + DirectML ---
    try:
        from mneme.embeddings.onnx_provider import ONNXProvider
        provider = ONNXProvider("BAAI/bge-m3", backend="directml")
        r = benchmark_embedding_provider(provider, chunks_texts, "ONNX Runtime + DirectML (AMD GPU)")
        results.append(r)
        del provider
        gc.collect()
    except Exception as e:
        print(f"\n  ONNX DirectML FAILED: {e}")

    # --- Summary ---
    print(f"\n{'='*60}")
    print("BENCHMARK RESULTS")
    print(f"{'='*60}")
    print(f"{'Backend':<35} {'Embed(s)':<10} {'Ch/s':<10} {'RAM(MB)':<10} {'Search(ms)':<10}")
    print("-" * 75)
    for r in results:
        print(f"{r['label']:<35} {r['embed_time_s']:<10} {r['throughput']:<10} {r['ram_peak_mb']:<10} {r['search_avg_ms']:<10}")


if __name__ == "__main__":
    main()
