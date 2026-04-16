"""Benchmark INT8-quantized BGE-M3 ONNX with DirectML (AMD GPU)."""

import os
import sys
import time
import statistics

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def get_mem_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def main():
    import sqlite3
    from mneme.config import load_config

    config = load_config()
    conn = sqlite3.connect(str(config.db_path))
    rows = conn.execute("SELECT content FROM chunks").fetchall()
    conn.close()
    chunks = [r[0] for r in rows]
    print(f"Chunks: {len(chunks)}")

    # Use xenova/bge-m3 which has INT8 quantized ONNX
    from mneme.embeddings.onnx_provider import ONNXProvider

    # Test 1: INT8 ONNX on DirectML
    print("\n=== INT8 ONNX + DirectML ===")
    try:
        provider = ONNXProvider("BAAI/bge-m3", backend="directml", onnx_model_name="xenova/bge-m3")
        mem0 = get_mem_mb()
        t0 = time.monotonic()
        provider.warmup()
        load_time = time.monotonic() - t0
        mem1 = get_mem_mb()
        print(f"  Loaded in {load_time:.1f}s, RAM: {mem0:.0f} → {mem1:.0f} MB")

        print(f"  Embedding {len(chunks)} chunks...")
        t0 = time.monotonic()
        for i in range(0, len(chunks), 32):
            provider.embed(chunks[i:i+32])
        embed_time = time.monotonic() - t0
        mem2 = get_mem_mb()
        print(f"  Done in {embed_time:.1f}s ({len(chunks)/embed_time:.1f} ch/s)")
        print(f"  RAM: {mem2:.0f} MB")

        queries = ["KI-Strategie", "RAG Pipeline", "Obsidian Vault", "Python Code",
                   "Web3 Blockchain", "Projektmanagement", "Embeddings", "Wissensmanagement",
                   "Trading", "Weiterbildung"]
        times = []
        for q in queries:
            t = time.monotonic()
            provider.embed([q])
            times.append((time.monotonic() - t) * 1000)
        print(f"  Search avg: {statistics.mean(times):.1f}ms")
    except Exception as e:
        print(f"  FAILED: {e}")

    # Test 2: INT8 ONNX on CPU (comparison)
    print("\n=== INT8 ONNX + CPU ===")
    try:
        provider2 = ONNXProvider("BAAI/bge-m3", backend="cpu", onnx_model_name="xenova/bge-m3")
        t0 = time.monotonic()
        provider2.warmup()
        load_time = time.monotonic() - t0
        print(f"  Loaded in {load_time:.1f}s")

        print(f"  Embedding {len(chunks)} chunks...")
        t0 = time.monotonic()
        for i in range(0, len(chunks), 32):
            provider2.embed(chunks[i:i+32])
        embed_time = time.monotonic() - t0
        print(f"  Done in {embed_time:.1f}s ({len(chunks)/embed_time:.1f} ch/s)")
    except Exception as e:
        print(f"  FAILED: {e}")


if __name__ == "__main__":
    main()
