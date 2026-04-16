"""Mneme GPU Benchmark — tests device, batch_size, and dtype combinations."""

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


def get_gpu_memory():
    """Get GPU memory usage if available."""
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / (1024 ** 3)
            reserved = torch.cuda.memory_reserved() / (1024 ** 3)
            return allocated, reserved
    except Exception:
        pass
    return 0.0, 0.0


def benchmark_config(chunks_texts, device, dtype, batch_size, label):
    """Benchmark a specific device/dtype/batch_size combination."""
    from mneme.embeddings.sentence_transformers import SentenceTransformersProvider

    print(f"\n{'='*60}")
    print(f"Benchmark: {label}")
    print(f"  device={device}, dtype={dtype}, batch_size={batch_size}")
    print(f"{'='*60}")

    provider = SentenceTransformersProvider(
        model_name="BAAI/bge-m3",
        device=device,
        dtype=dtype,
        batch_size=batch_size,
    )

    # Warmup (model load)
    mem_before = get_process_memory_mb()
    t0 = time.monotonic()
    provider.warmup()
    warmup_time = time.monotonic() - t0
    mem_after = get_process_memory_mb()
    gpu_alloc, gpu_reserved = get_gpu_memory()

    print(f"  Model loaded in {warmup_time:.1f}s")
    print(f"  RAM: {mem_before:.0f} -> {mem_after:.0f} MB (+{mem_after - mem_before:.0f} MB)")
    if gpu_alloc > 0:
        print(f"  VRAM: {gpu_alloc:.1f} GB allocated, {gpu_reserved:.1f} GB reserved")

    # Embedding throughput
    print(f"  Embedding {len(chunks_texts)} chunks (batch_size={batch_size})...")

    import torch
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t0 = time.monotonic()
    all_embeddings = provider.embed(chunks_texts)
    embed_time = time.monotonic() - t0
    throughput = len(chunks_texts) / embed_time

    gpu_alloc_after, gpu_reserved_after = get_gpu_memory()
    gpu_peak = 0.0
    try:
        if torch.cuda.is_available():
            gpu_peak = torch.cuda.max_memory_allocated() / (1024 ** 3)
    except Exception:
        pass

    print(f"  Embedded in {embed_time:.1f}s ({throughput:.1f} chunks/s)")
    if gpu_peak > 0:
        print(f"  VRAM peak: {gpu_peak:.1f} GB")

    # Search benchmark (10 queries)
    queries = [
        "KI-Strategie fuer Unternehmen",
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
        search_times.append((time.monotonic() - t0) * 1000)

    avg_search = statistics.mean(search_times)
    print(f"  Search (10 queries avg): {avg_search:.1f}ms")

    result = {
        "label": label,
        "device": device,
        "dtype": dtype,
        "batch_size": batch_size,
        "warmup_s": round(warmup_time, 1),
        "embed_time_s": round(embed_time, 1),
        "throughput": round(throughput, 1),
        "ram_mb": round(mem_after),
        "vram_peak_gb": round(gpu_peak, 1),
        "search_avg_ms": round(avg_search, 1),
        "dimension": len(all_embeddings[0]),
    }

    # Cleanup
    del provider
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()

    return result


def main():
    import sqlite3
    from mneme.config import load_config

    config = load_config()

    # Load chunk texts from DB
    conn = sqlite3.connect(str(config.db_path))
    rows = conn.execute("SELECT content FROM chunks").fetchall()
    conn.close()
    chunks_texts = [r[0] for r in rows]
    print(f"Loaded {len(chunks_texts)} chunks from vault index")

    # Detect GPU
    from mneme.embeddings.sentence_transformers import detect_device
    device, is_rocm = detect_device("auto")
    print(f"Detected device: {device} (ROCm: {is_rocm})")

    results = []

    if device == "cuda":
        # --- GPU benchmarks ---

        # Batch size comparison (bfloat16)
        for bs in [32, 64, 128, 256]:
            try:
                r = benchmark_config(
                    chunks_texts, "cuda", "bfloat16", bs,
                    f"GPU bfloat16 bs={bs}",
                )
                results.append(r)
            except Exception as e:
                print(f"\n  FAILED (bs={bs}): {e}")

        # dtype comparison (best batch size from above, or 128)
        best_bs = 128
        if results:
            best_bs = min(results, key=lambda r: r["embed_time_s"])["batch_size"]
            print(f"\nBest batch size so far: {best_bs}")

        for dt in ["float16", "float32"]:
            try:
                r = benchmark_config(
                    chunks_texts, "cuda", dt, best_bs,
                    f"GPU {dt} bs={best_bs}",
                )
                results.append(r)
            except Exception as e:
                print(f"\n  FAILED ({dt}): {e}")

        # CPU baseline for comparison
        try:
            r = benchmark_config(
                chunks_texts, "cpu", "bfloat16", 32,
                "CPU bfloat16 bs=32 (baseline)",
            )
            results.append(r)
        except Exception as e:
            print(f"\n  CPU baseline FAILED: {e}")

    else:
        # --- CPU-only benchmarks ---
        for dt in ["bfloat16", "float16", "float32"]:
            try:
                r = benchmark_config(
                    chunks_texts, "cpu", dt, 32,
                    f"CPU {dt} bs=32",
                )
                results.append(r)
            except Exception as e:
                print(f"\n  FAILED ({dt}): {e}")

    # --- Summary ---
    print(f"\n{'='*80}")
    print("BENCHMARK RESULTS")
    print(f"{'='*80}")
    header = f"{'Config':<30} {'Embed(s)':<10} {'Ch/s':<10} {'VRAM(GB)':<10} {'RAM(MB)':<10} {'Search(ms)':<10}"
    print(header)
    print("-" * 80)
    for r in results:
        vram = f"{r['vram_peak_gb']}" if r["vram_peak_gb"] > 0 else "-"
        print(f"{r['label']:<30} {r['embed_time_s']:<10} {r['throughput']:<10} {vram:<10} {r['ram_mb']:<10} {r['search_avg_ms']:<10}")

    if len(results) >= 2:
        fastest = min(results, key=lambda r: r["embed_time_s"])
        slowest = max(results, key=lambda r: r["embed_time_s"])
        print(f"\nFastest: {fastest['label']} ({fastest['embed_time_s']}s, {fastest['throughput']} ch/s)")
        print(f"Slowest: {slowest['label']} ({slowest['embed_time_s']}s)")
        if slowest["embed_time_s"] > 0:
            speedup = slowest["embed_time_s"] / fastest["embed_time_s"]
            print(f"Speedup: {speedup:.1f}x")


if __name__ == "__main__":
    main()
