"""ONNX Runtime embedding provider with GPU backend support.

Supports CPU, DirectML (AMD/Intel/NVIDIA on Windows), CUDA (NVIDIA), and ROCm (AMD Linux).
Uses onnxruntime directly with the HuggingFace tokenizer for maximum control.

Optional dependencies:
  - onnxruntime          (CPU)
  - onnxruntime-directml (DirectML / Windows GPU)
  - onnxruntime-gpu      (CUDA / NVIDIA)

Install via:  pip install mneme[onnx]  /  mneme[directml]  /  mneme[cuda]
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from mneme.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort

    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False
    ort = None  # type: ignore[assignment]


# Mapping from friendly backend name → ONNX Runtime Execution Provider name
_BACKEND_TO_EP: dict[str, str] = {
    "cpu": "CPUExecutionProvider",
    "directml": "DmlExecutionProvider",
    "cuda": "CUDAExecutionProvider",
    "rocm": "ROCMExecutionProvider",
}

class ONNXProvider(EmbeddingProvider):
    """Embedding provider using ONNX Runtime.

    Parameters
    ----------
    model_name:
        HuggingFace model ID.  If it contains an ONNX model file it will be
        used directly; otherwise the model is downloaded/cached via
        huggingface_hub.
    backend:
        One of ``"cpu"`` | ``"directml"`` | ``"cuda"`` | ``"rocm"``.
        Falls back to CPU with a warning if the requested backend is
        unavailable.
    onnx_model_name:
        Optional override for the ONNX model repo (e.g. ``"aapot/bge-m3-onnx"``).
        If *None*, uses a known ONNX conversion of the base model when available.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        backend: str = "cpu",
        onnx_model_name: str | None = None,
    ) -> None:
        if not HAS_ONNX:
            raise ImportError(
                "onnxruntime is not installed.  "
                "Install it with:  pip install onnxruntime  "
                "(or onnxruntime-directml / onnxruntime-gpu for GPU support)"
            )

        self.model_name = model_name
        self.backend = backend.lower()
        self.onnx_model_name = onnx_model_name
        self._session: ort.InferenceSession | None = None  # type: ignore[union-attr]
        self._tokenizer = None
        self._dimension: int | None = None

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------

    def _resolve_providers(self) -> list[str]:
        """Return the list of Execution Providers to request, with fallback."""
        requested_ep = _BACKEND_TO_EP.get(self.backend)
        if requested_ep is None:
            logger.warning(
                "Unknown backend '%s' — falling back to CPU.  "
                "Valid options: %s",
                self.backend,
                ", ".join(_BACKEND_TO_EP.keys()),
            )
            return ["CPUExecutionProvider"]

        available = ort.get_available_providers()  # type: ignore[union-attr]

        if requested_ep in available:
            # Always keep CPU as last fallback so individual ops can run there
            providers = [requested_ep]
            if "CPUExecutionProvider" not in providers:
                providers.append("CPUExecutionProvider")
            return providers

        logger.warning(
            "Requested backend '%s' (EP: %s) is not available.  "
            "Available providers: %s — falling back to CPU.",
            self.backend,
            requested_ep,
            ", ".join(available),
        )
        return ["CPUExecutionProvider"]

    def _resolve_onnx_model_path(self) -> str:
        """Download / locate the ONNX model and return the directory path."""
        from huggingface_hub import snapshot_download

        # Use explicit ONNX repo if provided, otherwise use known mapping
        repo_id = self.onnx_model_name
        if repo_id is None:
            # Known ONNX conversions for popular models
            _ONNX_REPOS: dict[str, str] = {
                "BAAI/bge-m3": "aapot/bge-m3-onnx",
            }
            repo_id = _ONNX_REPOS.get(self.model_name)

        if repo_id is None:
            raise ValueError(
                f"No known ONNX conversion for model '{self.model_name}'.  "
                f"Provide an explicit onnx_model_name parameter pointing to a "
                f"HuggingFace repo with an ONNX model."
            )

        logger.info("Downloading / caching ONNX model: %s", repo_id)
        model_dir = snapshot_download(repo_id)
        return model_dir

    def _find_onnx_file(self, model_dir: str) -> str:
        """Find the .onnx file inside a model directory."""
        onnx_files = list(Path(model_dir).glob("*.onnx"))
        if not onnx_files:
            # Check subdirectories (some repos use onnx/ subfolder)
            onnx_files = list(Path(model_dir).rglob("*.onnx"))
        if not onnx_files:
            raise FileNotFoundError(
                f"No .onnx file found in {model_dir}.  "
                f"Make sure the repo contains a pre-converted ONNX model."
            )
        # Prefer model.onnx or model_optimized.onnx
        for preferred in ("model_optimized.onnx", "model.onnx"):
            for f in onnx_files:
                if f.name == preferred:
                    return str(f)
        return str(onnx_files[0])

    def _load_model(self) -> ort.InferenceSession:  # type: ignore[name-defined]
        """Lazy-load tokenizer and ONNX session."""
        if self._session is not None:
            return self._session

        logger.info(
            "Loading ONNX embedding model: %s (backend: %s)",
            self.model_name,
            self.backend,
        )
        t0 = time.monotonic()

        # 1. Tokenizer — always from the original model
        from transformers import AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        t1 = time.monotonic()
        logger.info("  tokenizer loaded: %.1fs", t1 - t0)

        # 2. ONNX model
        model_dir = self._resolve_onnx_model_path()
        onnx_path = self._find_onnx_file(model_dir)
        t2 = time.monotonic()
        logger.info("  model resolved: %s (%.1fs)", onnx_path, t2 - t1)

        # 3. Session
        providers = self._resolve_providers()
        logger.info("  execution providers: %s", providers)

        sess_options = ort.SessionOptions()  # type: ignore[union-attr]
        sess_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL  # type: ignore[union-attr]
        )

        self._session = ort.InferenceSession(  # type: ignore[union-attr]
            onnx_path,
            sess_options=sess_options,
            providers=providers,
        )
        t3 = time.monotonic()
        logger.info("  ONNX session created: %.1fs", t3 - t2)
        logger.info("  total load time: %.1fs", t3 - t0)

        # Log which EP was actually selected
        active_providers = self._session.get_providers()
        logger.info("  active providers: %s", active_providers)

        return self._session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """Pre-load model. Call at startup to avoid first-query latency."""
        self._load_model()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Compute normalized dense embeddings for a batch of texts."""
        session = self._load_model()

        # Tokenize
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="np",
        )

        # Build ONNX inputs — only pass what the model expects
        input_names = {inp.name for inp in session.get_inputs()}
        onnx_inputs = {
            k: v for k, v in encoded.items() if k in input_names
        }

        # Run inference
        outputs = session.run(None, onnx_inputs)

        # The first output is typically dense embeddings or token embeddings.
        # For bge-m3-onnx (aapot), output[0] = dense embeddings (already pooled).
        # For raw transformer ONNX exports, output[0] = token embeddings
        # and we need to do mean pooling ourselves.
        embeddings = outputs[0]

        # If output is 3D (batch, seq_len, hidden) → mean pooling needed
        if embeddings.ndim == 3:
            attention_mask = encoded["attention_mask"]
            mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(
                embeddings.dtype
            )
            sum_embeddings = np.sum(embeddings * mask_expanded, axis=1)
            sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
            embeddings = sum_embeddings / sum_mask

        # L2-normalize
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)
        embeddings = embeddings / norms

        # Cache dimension
        if self._dimension is None:
            self._dimension = embeddings.shape[1]

        return embeddings.tolist()

    def dimension(self) -> int:
        """Return embedding dimension. Triggers model load if unknown."""
        if self._dimension is not None:
            return self._dimension
        # Need to run a dummy inference to determine dimension
        self.embed(["dimension probe"])
        assert self._dimension is not None
        return self._dimension
