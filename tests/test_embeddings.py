import math

import pytest

from mneme.embeddings import get_provider
from mneme.embeddings.sentence_transformers import SentenceTransformersProvider


class MockConfig:
    def __init__(self, provider="sentence-transformers", model="BAAI/bge-m3"):
        self.provider = provider
        self.model = model


@pytest.fixture(scope="module")
def provider():
    return SentenceTransformersProvider("BAAI/bge-m3")


# --- non-slow tests ---

def test_factory_sentence_transformers():
    result = get_provider(MockConfig(provider="sentence-transformers"))
    assert isinstance(result, SentenceTransformersProvider)


def test_factory_unknown_provider():
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        get_provider(MockConfig(provider="unknown"))


def test_lazy_loading():
    p = SentenceTransformersProvider("BAAI/bge-m3")
    assert p._model is None


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
