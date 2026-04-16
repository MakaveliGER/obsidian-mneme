"""Single-backend benchmark — run one at a time to avoid memory interference."""

import gc
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


def run(backend_name):
    import sqlite3
    from mneme.config import load_config

    config = load_config()
    conn = sqlite3.connect(str(config.db_path))
    rows = conn.execute("SELECT content FROM chunks").fetchall()
    conn.close()
    chunks = [r[0] for r in rows]
    print(f"Chunks: {len(chunks)}")

    if backend_name == "pytorch-cpu":
        from mneme.embeddings.sentence_transformers import SentenceTransformersProvider
        provider = SentenceTransformersProvider("BAAI/bge-m3")
    elif backend_name == "onnx-cpu":
        from mneme.embeddings.onnx_provider import ONNXProvider
        provider = ONNXProvider("BAAI/bge-m3", backend="cpu")
    elif backend_name == "onnx-directml":
        from mneme.embeddings.onnx_provider import ONNXProvider
        provider = ONNXProvider("BAAI/bge-m3", backend="directml")
    elif backend_name == "pytorch-rocm":
        # Test if ROCm is available via PyTorch
        import torch
        print(f"PyTorch version: {torch.__version__}")
        print(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"Device: {torch.cuda.get_device_name(0)}")
            print(f"VRAM: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB")
        from mneme.embeddings.sentence_transformers import SentenceTransformersProvider
        provider = SentenceTransformersProvider("BAAI/bge-m3")
        # sentence-transformers auto-uses CUDA if available
    else:
        print(f"Unknown backend: {backend_name}")
        return

    mem0 = get_mem_mb()
    print(f"\nLoading model ({backend_name})...")
    t0 = time.monotonic()
    if hasattr(provider, "warmup"):
        provider.warmup()
    else:
        provider.embed(["warmup"])
    load_time = time.monotonic() - t0
    mem1 = get_mem_mb()
    print(f"  Loaded in {load_time:.1f}s, RAM: {mem0:.0f} → {mem1:.0f} MB (+{mem1-mem0:.0f} MB)")

    print(f"\nEmbedding {len(chunks)} chunks (batch=32)...")
    t0 = time.monotonic()
    for i in range(0, len(chunks), 32):
        provider.embed(chunks[i:i+32])
    embed_time = time.monotonic() - t0
    mem2 = get_mem_mb()
    throughput = len(chunks) / embed_time
    print(f"  Done in {embed_time:.1f}s ({throughput:.1f} chunks/s)")
    print(f"  RAM peak: {mem2:.0f} MB")

    # Search
    queries = ["KI-Strategie", "RAG Pipeline", "Obsidian Vault", "Python Code",
               "Web3 Blockchain", "Projektmanagement", "Embeddings", "Wissensmanagement",
               "Trading", "Weiterbildung"]
    times = []
    for q in queries:
        t = time.monotonic()
        provider.embed([q])
        times.append((time.monotonic() - t) * 1000)
    print(f"  Search avg: {statistics.mean(times):.1f}ms")

    print(f"\n{'='*50}")
    print(f"RESULT: {backend_name}")
    print(f"  Load:      {load_time:.1f}s")
    print(f"  Embed:     {embed_time:.1f}s ({throughput:.1f} ch/s)")
    print(f"  RAM:       {mem2:.0f} MB")
    print(f"  Search:    {statistics.mean(times):.1f}ms")
    print(f"{'='*50}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python bench_single.py <pytorch-cpu|onnx-cpu|onnx-directml|pytorch-rocm>")
        sys.exit(1)
    run(sys.argv[1])
