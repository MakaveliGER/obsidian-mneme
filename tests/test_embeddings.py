import math
from unittest.mock import patch, MagicMock

import pytest

from mneme.embeddings import get_provider
from mneme.embeddings.sentence_transformers import (
    SentenceTransformersProvider,
    detect_device,
)


class MockConfig:
    def __init__(self, provider="sentence-transformers", model="BAAI/bge-m3",
                 device="cpu", dtype="bfloat16", batch_size=32):
        self.provider = provider
        self.model = model
        self.device = device
        self.dtype = dtype
        self.batch_size = batch_size


@pytest.fixture(scope="module")
def provider():
    return SentenceTransformersProvider("BAAI/bge-m3")


# --- non-slow tests ---

def test_factory_sentence_transformers():
    result = get_provider(MockConfig(provider="sentence-transformers"))
    assert isinstance(result, SentenceTransformersProvider)


def test_factory_passes_config_fields():
    result = get_provider(MockConfig(device="cpu", dtype="float16", batch_size=128))
    assert result._requested_device == "cpu"
    assert result._dtype_name == "float16"
    assert result.batch_size == 128


def test_factory_unknown_provider():
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        get_provider(MockConfig(provider="unknown"))


def test_lazy_loading():
    p = SentenceTransformersProvider("BAAI/bge-m3")
    assert p._model is None


def test_constructor_stores_config():
    p = SentenceTransformersProvider("BAAI/bge-m3", device="cuda", dtype="float16", batch_size=256)
    assert p._requested_device == "cuda"
    assert p._dtype_name == "float16"
    assert p.batch_size == 256


def test_detect_device_cpu():
    device, is_rocm = detect_device("cpu")
    assert device == "cpu"
    assert is_rocm is False


def _mock_torch(cuda_available=False, device_name=""):
    """Create a mock torch module for detect_device tests."""
    mock = MagicMock()
    mock.cuda.is_available.return_value = cuda_available
    mock.cuda.get_device_name.return_value = device_name
    return mock


def test_detect_device_cuda_not_available():
    mock = _mock_torch(cuda_available=False)
    with patch.dict("sys.modules", {"torch": mock}):
        device, is_rocm = detect_device("cuda")
        assert device == "cpu"
        assert is_rocm is False


def test_detect_device_cuda_nvidia():
    mock = _mock_torch(cuda_available=True, device_name="NVIDIA GeForce RTX 4090")
    with patch.dict("sys.modules", {"torch": mock}):
        device, is_rocm = detect_device("cuda")
        assert device == "cuda"
        assert is_rocm is False


def test_detect_device_cuda_amd():
    mock = _mock_torch(cuda_available=True, device_name="AMD Radeon RX 7900 XTX")
    with patch.dict("sys.modules", {"torch": mock}):
        device, is_rocm = detect_device("cuda")
        assert device == "cuda"
        assert is_rocm is True


def test_detect_device_auto_no_gpu():
    mock = _mock_torch(cuda_available=False)
    with patch.dict("sys.modules", {"torch": mock}):
        device, is_rocm = detect_device("auto")
        assert device == "cpu"
        assert is_rocm is False


# --- slow tests ---

@pytest.mark.slow
def test_embed_returns_correct_shape(provider):
    vectors = provider.embed(["Hello world"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024


@pytest.mark.slow
def test_embed_batch(provider):
    texts = ["First text", "Second text", "Third text"]
    vectors = provider.embed(texts)
    assert len(vectors) == 3


@pytest.mark.slow
def test_vectors_normalized(provider):
    vectors = provider.embed(["Normalize me"])
    for vec in vectors:
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-3, f"L2-Norm {norm} ist nicht ≈ 1.0"


@pytest.mark.slow
def test_dimension(provider):
    assert provider.dimension() == 1024
