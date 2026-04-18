"""Dev-only: verify byte-parity between sentence_transformers and raw_transformers.

Loads both providers on CPU with float32, encodes five probe strings,
and asserts ``numpy.allclose(a, b, atol=1e-6)``. Downloads the BGE-M3
model on first run (~2 GB). Run manually:

    uv run python scripts/verify_provider_parity.py
"""

from __future__ import annotations

import sys
import time

import numpy as np

from mneme.embeddings.raw_transformers import RawBgeM3Provider
from mneme.embeddings.sentence_transformers import SentenceTransformersProvider


PROBES = [
    "The quick brown fox jumps over the lazy dog.",
    "Semantische Suche über einen Obsidian-Vault.",
    "",  # empty string edge case
    "BGE-M3 uses CLS pooling and L2 normalization.",
    "x" * 4096,  # long input (will be truncated)
]


def main() -> int:
    print("Loading sentence_transformers provider (CPU, float32)...")
    t0 = time.monotonic()
    st = SentenceTransformersProvider(
        "BAAI/bge-m3", device="cpu", dtype="float32", batch_size=4
    )
    st_vecs = np.asarray(st.embed(PROBES), dtype=np.float64)
    t1 = time.monotonic()
    print(f"  done ({t1 - t0:.1f}s) → shape {st_vecs.shape}")

    print("Loading raw_transformers provider (CPU, float32)...")
    rt = RawBgeM3Provider(
        "BAAI/bge-m3", device="cpu", dtype="float32", batch_size=4
    )
    rt_vecs = np.asarray(rt.embed(PROBES), dtype=np.float64)
    t2 = time.monotonic()
    print(f"  done ({t2 - t1:.1f}s) → shape {rt_vecs.shape}")

    assert st_vecs.shape == rt_vecs.shape, (
        f"shape mismatch: {st_vecs.shape} vs {rt_vecs.shape}"
    )

    diff = np.abs(st_vecs - rt_vecs)
    max_abs = float(diff.max())
    mean_abs = float(diff.mean())
    print(f"max |diff|  = {max_abs:.2e}")
    print(f"mean |diff| = {mean_abs:.2e}")

    atol = 1e-6
    if np.allclose(st_vecs, rt_vecs, atol=atol):
        print(f"PASS — vectors match within atol={atol}")
        return 0

    print(f"FAIL — vectors differ beyond atol={atol}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
