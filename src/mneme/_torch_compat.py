"""Shim for torch on platforms where `torch.distributed` is stubbed.

ROCm PyTorch wheels on Windows ship without a functional `torch.distributed`
module. sentence-transformers calls `torch.distributed.is_initialized()` /
`get_rank()` unconditionally, so we monkey-patch safe no-ops at import time.

Importing this module from any entry point that later loads sentence-transformers
(embedder, reranker) ensures the patch is in place before the first call.
"""

from __future__ import annotations

try:
    import torch

    if not hasattr(torch, "distributed"):
        class _DummyDistributed:
            pass
        torch.distributed = _DummyDistributed()
    if not hasattr(torch.distributed, "is_initialized"):
        torch.distributed.is_initialized = lambda: False
    if not hasattr(torch.distributed, "get_rank"):
        torch.distributed.get_rank = lambda: 0
except ImportError:
    # torch not installed — nothing to patch.
    pass
