"""Tests for the raw-transformers BGE-M3 provider."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from mneme.embeddings import get_provider
from mneme.embeddings.raw_transformers import RawBgeM3Provider


class MockConfig:
    def __init__(
        self,
        provider: str = "raw-transformers",
        model: str = "BAAI/bge-m3",
        device: str = "cpu",
        dtype: str = "float32",
        batch_size: int = 32,
    ):
        self.provider = provider
        self.model = model
        self.device = device
        self.dtype = dtype
        self.batch_size = batch_size


# ----------------------------------------------------------------------
# Factory wiring
# ----------------------------------------------------------------------

def test_factory_creates_raw_transformers_provider():
    result = get_provider(MockConfig(provider="raw-transformers"))
    assert isinstance(result, RawBgeM3Provider)


def test_factory_passes_config_fields():
    result = get_provider(
        MockConfig(
            provider="raw-transformers",
            device="cpu",
            dtype="float16",
            batch_size=128,
        )
    )
    assert isinstance(result, RawBgeM3Provider)
    assert result._requested_device == "cpu"
    assert result._dtype_name == "float16"
    assert result.batch_size == 128


# ----------------------------------------------------------------------
# Constructor / lazy loading
# ----------------------------------------------------------------------

def test_constructor_stores_config():
    p = RawBgeM3Provider(
        "BAAI/bge-m3", device="cuda", dtype="float16", batch_size=256
    )
    assert p.model_name == "BAAI/bge-m3"
    assert p._requested_device == "cuda"
    assert p._dtype_name == "float16"
    assert p.batch_size == 256


def test_lazy_loading_no_model_on_construct():
    p = RawBgeM3Provider("BAAI/bge-m3")
    assert p._model is None
    assert p._tokenizer is None


# ----------------------------------------------------------------------
# Unit tests for the encoding path (model is mocked — no download)
# ----------------------------------------------------------------------

def _make_mocked_provider(hidden_size: int = 1024, device: str = "cpu"):
    """Return a RawBgeM3Provider whose _load_model() is patched out.

    Populates ``_model`` with a callable mock returning a fake
    ``last_hidden_state`` and ``_tokenizer`` with a callable mock returning
    tensors. Avoids any HuggingFace download.
    """
    import torch

    p = RawBgeM3Provider("BAAI/bge-m3", device=device, dtype="float32", batch_size=2)
    p._device = device
    p._dimension = hidden_size

    def fake_tokenizer(batch, **kwargs):
        n = len(batch)
        seq_len = 4
        return {
            "input_ids": torch.ones((n, seq_len), dtype=torch.long),
            "attention_mask": torch.ones((n, seq_len), dtype=torch.long),
        }

    tokenizer_mock = MagicMock(side_effect=fake_tokenizer)
    p._tokenizer = tokenizer_mock

    def fake_forward(**kwargs):
        batch_size = kwargs["input_ids"].shape[0]
        seq_len = kwargs["input_ids"].shape[1]
        # Deterministic non-zero CLS embedding so L2-norm is non-trivial.
        last_hidden_state = torch.ones(
            (batch_size, seq_len, hidden_size), dtype=torch.float32
        )
        for i in range(batch_size):
            last_hidden_state[i, 0, :] = float(i + 1)
        out = MagicMock()
        out.last_hidden_state = last_hidden_state
        return out

    model_mock = MagicMock(side_effect=fake_forward)
    p._model = model_mock

    # Short-circuit _load_model — it returns the already-set mock.
    return p, tokenizer_mock, model_mock


def test_embed_returns_list_of_lists_of_floats():
    p, _tok, _mdl = _make_mocked_provider(hidden_size=8)
    vectors = p.embed(["hello", "world"])
    assert isinstance(vectors, list)
    assert len(vectors) == 2
    for v in vectors:
        assert isinstance(v, list)
        assert len(v) == 8
        assert all(isinstance(x, float) for x in v)


def test_embed_vectors_are_l2_normalized():
    p, _tok, _mdl = _make_mocked_provider(hidden_size=8)
    vectors = p.embed(["a", "b", "c"])
    for v in vectors:
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 1e-5, f"L2 norm {norm} != 1.0"


def test_embed_batches_respect_batch_size():
    """batch_size=2 over 5 texts → 3 forward passes (2+2+1)."""
    p, tok, mdl = _make_mocked_provider(hidden_size=8)
    p.batch_size = 2
    _ = p.embed(["t1", "t2", "t3", "t4", "t5"])
    # Tokenizer + model called once per mini-batch
    assert tok.call_count == 3
    assert mdl.call_count == 3


def test_embed_empty_input():
    p, _tok, _mdl = _make_mocked_provider(hidden_size=8)
    assert p.embed([]) == []


def test_dimension_from_cached_value():
    p = RawBgeM3Provider("BAAI/bge-m3")
    p._dimension = 1024
    assert p.dimension() == 1024


# ----------------------------------------------------------------------
# Dimension reads config.hidden_size without a dummy forward pass.
# We patch AutoModel/AutoTokenizer so no weights get downloaded.
# ----------------------------------------------------------------------

def test_dimension_reads_model_config_hidden_size():
    with patch("transformers.AutoModel") as mock_model_cls, patch(
        "transformers.AutoTokenizer"
    ) as mock_tok_cls:
        fake_model = MagicMock()
        fake_model.config.hidden_size = 1024
        fake_model.eval.return_value = fake_model
        fake_model.to.return_value = fake_model
        mock_model_cls.from_pretrained.return_value = fake_model
        mock_tok_cls.from_pretrained.return_value = MagicMock()

        p = RawBgeM3Provider("BAAI/bge-m3", device="cpu", dtype="float32")
        assert p.dimension() == 1024


# ----------------------------------------------------------------------
# Integration test — real BGE-M3. Opt-in via `-m slow` (same marker as
# the sentence_transformers provider tests).
# ----------------------------------------------------------------------

@pytest.mark.slow
def test_integration_real_bge_m3_dimension_and_norm():
    p = RawBgeM3Provider("BAAI/bge-m3", device="cpu", dtype="float32")
    vectors = p.embed(["test text"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024
    norm = math.sqrt(sum(x * x for x in vectors[0]))
    assert abs(norm - 1.0) < 1e-3
