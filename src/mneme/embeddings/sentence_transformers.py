import logging
import os
import time

# Apply the torch.distributed shim before anything may trigger a
# sentence-transformers import.
from mneme import _torch_compat  # noqa: F401
from mneme.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

def detect_device(requested: str = "auto") -> tuple[str, bool]:
    """Detect the best available compute device.

    Args:
        requested: "auto", "cpu", or "cuda".

    Returns:
        Tuple of (device_string, is_rocm).
        device_string is "cuda" or "cpu".
        is_rocm is True when the GPU is AMD (ROCm backend).
    """
    if requested == "cpu":
        return "cpu", False

    if requested == "cuda":
        import torch
        if not torch.cuda.is_available():
            logger.warning("CUDA requested but not available — falling back to CPU")
            return "cpu", False
        name = torch.cuda.get_device_name(0)
        is_rocm = any(k in name.lower() for k in ("radeon", "amd", "gfx"))
        return "cuda", is_rocm

    # auto detection
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            is_rocm = any(k in name.lower() for k in ("radeon", "amd", "gfx"))
            logger.info("GPU detected: %s (%s)", name, "ROCm" if is_rocm else "CUDA")
            return "cuda", is_rocm
    except Exception as e:
        logger.debug("GPU detection failed: %s", e)

    logger.info("No GPU detected — using CPU")
    return "cpu", False


def _check_sdpa_backends(device: str) -> None:
    """Log which SDPA backends are available on the current device."""
    try:
        import torch
        from torch.nn.functional import scaled_dot_product_attention

        q = torch.randn(1, 8, 128, 64, device=device, dtype=torch.float16)
        k = torch.randn(1, 8, 128, 64, device=device, dtype=torch.float16)
        v = torch.randn(1, 8, 128, 64, device=device, dtype=torch.float16)

        # Use new API (sdpa_kernel) if available, fall back to deprecated sdp_kernel
        try:
            from torch.nn.attention import SDPBackend, sdpa_kernel
            backend_map = {
                "flash": [SDPBackend.FLASH_ATTENTION],
                "mem_efficient": [SDPBackend.EFFICIENT_ATTENTION],
                "math": [SDPBackend.MATH],
            }
            results = []
            for name, backends in backend_map.items():
                try:
                    with sdpa_kernel(backends):
                        scaled_dot_product_attention(q, k, v)
                    results.append(f"{name}=OK")
                except Exception:
                    results.append(f"{name}=FAIL")
        except ImportError:
            # Fallback: old API (PyTorch < 2.5)
            backend_map_old = {
                "flash": {"enable_flash": True, "enable_mem_efficient": False, "enable_math": False},
                "mem_efficient": {"enable_flash": False, "enable_mem_efficient": True, "enable_math": False},
                "math": {"enable_flash": False, "enable_mem_efficient": False, "enable_math": True},
            }
            results = []
            for name, kwargs in backend_map_old.items():
                try:
                    with torch.backends.cuda.sdp_kernel(**kwargs):
                        scaled_dot_product_attention(q, k, v)
                    results.append(f"{name}=OK")
                except Exception:
                    results.append(f"{name}=FAIL")

        logger.info("SDPA backends: %s", ", ".join(results))
    except Exception as e:
        logger.debug("SDPA backend check skipped: %s", e)


class SentenceTransformersProvider(EmbeddingProvider):
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
        self._device = None  # resolved device string

    def _load_model(self):
        if self._model is not None:
            return self._model

        logger.info("Loading embedding model: %s", self.model_name)
        t0 = time.monotonic()

        from sentence_transformers import SentenceTransformer

        t1 = time.monotonic()
        logger.info("  import sentence_transformers: %.1fs", t1 - t0)

        import torch

        # Detect device
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

        model_kwargs = {"dtype": torch_dtype}

        # SDPA is the best available attention on Windows (flash_attention_2 not available)
        if hasattr(torch, "bfloat16"):
            model_kwargs["attn_implementation"] = "sdpa"

        # Explicit trust_remote_code=False: never execute code from the
        # HuggingFace repo. Backstop in case MCP update_config's allowlist
        # is bypassed.
        self._model = SentenceTransformer(
            self.model_name,
            device=device,
            model_kwargs=model_kwargs,
            trust_remote_code=False,
        )
        t2 = time.monotonic()
        logger.info("  model loaded on %s (%s): %.1fs", device, self._dtype_name, t2 - t1)
        logger.info("  total load time: %.1fs", t2 - t0)

        if device == "cuda":
            mem_allocated = torch.cuda.memory_allocated() / (1024 ** 3)
            mem_reserved = torch.cuda.memory_reserved() / (1024 ** 3)
            logger.info("  VRAM: %.1f GB allocated, %.1f GB reserved", mem_allocated, mem_reserved)

        # Check SDPA backends (informational only)
        if device == "cuda":
            _check_sdpa_backends(device)

        return self._model

    def warmup(self) -> None:
        """Pre-load the model. Call at startup to avoid first-query latency."""
        self._load_model()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._load_model().encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=self.batch_size,
        ).tolist()

    def dimension(self) -> int:
        model = self._load_model()
        if hasattr(model, "get_embedding_dimension"):
            return model.get_embedding_dimension()
        return model.get_sentence_embedding_dimension()
