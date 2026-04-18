"""Raw `transformers` + `torch` embedding provider (no sentence_transformers).

Motivation
----------
sentence_transformers 5.x eagerly imports ``sklearn → scipy.special`` at
package import time, which triggers slow Windows ``LoadLibrary`` calls in
some Electron-spawned subprocess contexts (confirmed via faulthandler
stacktrace). This provider reproduces the BGE-M3 encoding path with only
``transformers.AutoModel`` + ``torch``, eliminating the sklearn/scipy
dependency on the hot import path.

BGE-M3 specifics
----------------
- Pooling: CLS (first token of ``last_hidden_state``)
- Normalization: L2 after pooling, cast to fp32 for a stable norm
- Tokenizer: XLMRobertaTokenizerFast (``use_fast=True``)
- Dense-only dimension: 1024

Parity with ``SentenceTransformersProvider`` is byte-exact in float32 on
CPU; in fp16/bf16 small numerical drift is expected.
"""

from __future__ import annotations

import logging
import os
import time

# Keep the torch.distributed shim — still useful for the reranker, and
# harmless for the forward pass here.
from mneme import _torch_compat  # noqa: F401
from mneme.embeddings.base import EmbeddingProvider

# Reuse device detection + SDPA probe from the sentence_transformers provider
# so both providers log the same ``GPU detected`` / ``SDPA backends`` lines.
from mneme.embeddings.sentence_transformers import (
    _check_sdpa_backends,
    detect_device,
)

logger = logging.getLogger(__name__)


class RawBgeM3Provider(EmbeddingProvider):
    """Embedding provider built directly on ``transformers.AutoModel``.

    Drop-in replacement for ``SentenceTransformersProvider`` for BGE-M3
    dense embeddings. Does not expose sparse / ColBERT heads — Mneme does
    not use them.
    """

    def __init__(
        self,
        model_name: str,
        device: str = "auto",
        dtype: str = "bfloat16",
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self._requested_device = device
        self._dtype_name = dtype
        self.batch_size = batch_size
        self._model = None
        self._tokenizer = None
        self._device = None  # resolved device string ("cpu" | "cuda")
        self._dimension: int | None = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_model(self):
        if self._model is not None:
            return self._model

        logger.info("[1/4] Loading embedding model: %s", self.model_name)
        t0 = time.monotonic()

        # torch import is explicit so we can pass dtype + move the model.
        import torch
        from transformers import AutoModel, AutoTokenizer

        t1 = time.monotonic()
        logger.info("[2/4] import transformers+torch: %.1fs", t1 - t0)

        # Device resolution shared with SentenceTransformersProvider.
        device, is_rocm = detect_device(self._requested_device)
        self._device = device

        # Enable AOTriton for ROCm (may unlock flash/mem_efficient SDPA kernels)
        if is_rocm:
            os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")
            logger.info("  ROCm detected — AOTriton experimental enabled")

        # Resolve dtype
        dtype_map = {
            "float32": torch.float32,
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
        }
        torch_dtype = dtype_map.get(self._dtype_name, torch.bfloat16)

        # Tokenizer — XLMRobertaTokenizerFast for BGE-M3.
        # trust_remote_code=False: never execute code from the HF repo.
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            use_fast=True,
            trust_remote_code=False,
        )
        t2 = time.monotonic()
        logger.info("[3/4] tokenizer loaded: %.1fs", t2 - t1)

        # Model — SDPA attention is the best available on Windows.
        self._model = AutoModel.from_pretrained(
            self.model_name,
            torch_dtype=torch_dtype,
            attn_implementation="sdpa",
            trust_remote_code=False,
        )
        self._model.eval()
        self._model.to(device)

        t3 = time.monotonic()
        logger.info(
            "[4/4] model loaded on %s (%s): %.1fs",
            device,
            self._dtype_name,
            t3 - t2,
        )
        logger.info("  total load time: %.1fs", t3 - t0)

        if device == "cuda":
            mem_allocated = torch.cuda.memory_allocated() / (1024 ** 3)
            mem_reserved = torch.cuda.memory_reserved() / (1024 ** 3)
            logger.info(
                "  VRAM: %.1f GB allocated, %.1f GB reserved",
                mem_allocated,
                mem_reserved,
            )
            _check_sdpa_backends(device)

        # Cache dimension from the config (cheap, no dummy forward).
        try:
            self._dimension = int(self._model.config.hidden_size)
        except Exception:
            self._dimension = None

        return self._model

    # ------------------------------------------------------------------
    # EmbeddingProvider API
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """Pre-load tokenizer + model. Call at startup to avoid first-query latency."""
        self._load_model()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode *texts* → list of 1024-dim L2-normalized vectors.

        Pipeline: tokenize → forward → CLS pool → L2-normalize (fp32).
        Output is ``list[list[float]]`` for pickle-safety with sqlite-vec.
        """
        import torch

        model = self._load_model()
        tokenizer = self._tokenizer
        assert tokenizer is not None  # _load_model sets both
        device = self._device

        out: list[list[float]] = []
        bs = max(1, int(self.batch_size))

        with torch.no_grad():
            for start in range(0, len(texts), bs):
                batch = texts[start : start + bs]
                encoded = tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=8192,
                    return_tensors="pt",
                )
                # Move to device (input_ids + attention_mask)
                encoded = {k: v.to(device) for k, v in encoded.items()}

                outputs = model(**encoded)
                # CLS pooling: first token of last_hidden_state
                cls = outputs.last_hidden_state[:, 0]

                # Cast to fp32 for a stable L2-norm, then normalize.
                cls = cls.to(torch.float32)
                cls = torch.nn.functional.normalize(cls, p=2, dim=1)

                out.extend(cls.cpu().tolist())

        return out

    def dimension(self) -> int:
        """Vector dimension. BGE-M3 = 1024 (from model config.hidden_size)."""
        if self._dimension is not None:
            return self._dimension
        # Load model to read config.hidden_size — cheaper than a dummy forward.
        self._load_model()
        assert self._dimension is not None
        return self._dimension
