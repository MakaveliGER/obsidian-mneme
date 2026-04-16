"""Tests for the ONNX embedding provider."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from mneme.embeddings import get_provider

# Check if onnxruntime is available
try:
    import onnxruntime

    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False


class MockConfig:
    def __init__(
        self,
        provider="onnx",
        model="BAAI/bge-m3",
        backend="cpu",
    ):
        self.provider = provider
        self.model = model
        self.backend = backend


# --- Tests that do NOT require onnxruntime ---


def test_factory_onnx_provider_import_error():
    """If onnxruntime is missing, get_provider('onnx') raises ImportError."""
    if HAS_ONNX:
        pytest.skip("onnxruntime is installed — cannot test import error")
    with pytest.raises(ImportError, match="onnxruntime"):
        get_provider(MockConfig(provider="onnx"))


# --- Tests that require onnxruntime ---


@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_factory_onnx_provider():
    """get_provider with provider='onnx' returns ONNXProvider."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    provider = get_provider(MockConfig(provider="onnx"))
    assert isinstance(provider, ONNXProvider)


@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_factory_onnx_provider_with_backend():
    """Backend is passed through from config."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    provider = get_provider(MockConfig(provider="onnx", backend="directml"))
    assert isinstance(provider, ONNXProvider)
    assert provider.backend == "directml"


@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_lazy_loading():
    """Creating provider should NOT load the model."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    p = ONNXProvider("BAAI/bge-m3", backend="cpu")
    assert p._session is None
    assert p._tokenizer is None


@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_backend_fallback(caplog):
    """Unavailable backend falls back to CPU with warning."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    p = ONNXProvider("BAAI/bge-m3", backend="cuda")
    providers = p._resolve_providers()

    # If CUDA is not actually available, should fall back to CPU
    available = onnxruntime.get_available_providers()
    if "CUDAExecutionProvider" not in available:
        assert providers == ["CPUExecutionProvider"]
        assert any("falling back to CPU" in r.message for r in caplog.records)


@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_unknown_backend_fallback(caplog):
    """Unknown backend name falls back to CPU with warning."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    with caplog.at_level(logging.WARNING):
        p = ONNXProvider("BAAI/bge-m3", backend="nonexistent")
        providers = p._resolve_providers()

    assert providers == ["CPUExecutionProvider"]
    assert any("Unknown backend" in r.message for r in caplog.records)


@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_cpu_provider_always_available():
    """CPU backend should always resolve successfully."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    p = ONNXProvider("BAAI/bge-m3", backend="cpu")
    providers = p._resolve_providers()
    assert "CPUExecutionProvider" in providers


@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_no_known_onnx_model():
    """Unknown model without explicit onnx_model_name raises ValueError."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    p = ONNXProvider("some-org/unknown-model", backend="cpu")
    with pytest.raises(ValueError, match="No known ONNX conversion"):
        p._resolve_onnx_model_path()


@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_factory_sentence_transformers_still_works():
    """Existing sentence-transformers provider is not broken."""
    from mneme.embeddings.sentence_transformers import SentenceTransformersProvider

    provider = get_provider(MockConfig(provider="sentence-transformers"))
    assert isinstance(provider, SentenceTransformersProvider)


def test_factory_unknown_provider():
    """Unknown provider still raises ValueError."""
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        get_provider(MockConfig(provider="unknown"))


# --- Slow integration tests (require model download) ---


@pytest.mark.slow
@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_embed_returns_correct_shape():
    """Full embedding round-trip with real ONNX model."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    p = ONNXProvider("BAAI/bge-m3", backend="cpu")
    vectors = p.embed(["Hello world"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024


@pytest.mark.slow
@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_embed_batch():
    """Batch embedding produces correct number of vectors."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    p = ONNXProvider("BAAI/bge-m3", backend="cpu")
    texts = ["First text", "Second text", "Third text"]
    vectors = p.embed(texts)
    assert len(vectors) == 3


@pytest.mark.slow
@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_vectors_normalized():
    """Embeddings should be L2-normalized."""
    import math

    from mneme.embeddings.onnx_provider import ONNXProvider

    p = ONNXProvider("BAAI/bge-m3", backend="cpu")
    vectors = p.embed(["Normalize me"])
    for vec in vectors:
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-3, f"L2-Norm {norm} ist nicht ≈ 1.0"


@pytest.mark.slow
@pytest.mark.skipif(not HAS_ONNX, reason="onnxruntime not installed")
def test_dimension():
    """dimension() should return 1024 for BGE-M3."""
    from mneme.embeddings.onnx_provider import ONNXProvider

    p = ONNXProvider("BAAI/bge-m3", backend="cpu")
    assert p.dimension() == 1024
