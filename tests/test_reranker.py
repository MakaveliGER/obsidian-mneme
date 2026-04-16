"""Tests for mneme.reranker.Reranker and SearchEngine integration with reranking."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mneme.store import SearchResult
from mneme.reranker import Reranker
from mneme.search import SearchEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_result(chunk_id: int, content: str = "content", score: float = 1.0) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        note_path=f"note{chunk_id}.md",
        note_title="Title",
        heading_path="",
        content=content,
        score=score,
        tags=[],
    )


def _make_reranker_with_mock(scores: list[float], threshold: float = 0.3) -> tuple[Reranker, MagicMock]:
    """Return a Reranker whose CrossEncoder.predict is mocked to return *scores*."""
    reranker = Reranker(model_name="mock-model", threshold=threshold)
    mock_model = MagicMock()
    mock_model.predict.return_value = scores
    reranker._model = mock_model
    return reranker, mock_model


# ---------------------------------------------------------------------------
# Reranker unit tests
# ---------------------------------------------------------------------------

def test_rerank_filters_below_threshold():
    """Results whose CrossEncoder score < threshold must be removed."""
    results = [make_result(1), make_result(2), make_result(3)]
    # scores: 1 above, 2 below, 3 above
    reranker, _ = _make_reranker_with_mock([0.8, 0.1, 0.5], threshold=0.3)

    output = reranker.rerank("query", results, top_k=10)

    chunk_ids = {r.chunk_id for r in output}
    assert 1 in chunk_ids, "score 0.8 >= threshold — must survive"
    assert 2 not in chunk_ids, "score 0.1 < threshold — must be filtered"
    assert 3 in chunk_ids, "score 0.5 >= threshold — must survive"


def test_rerank_sorts_by_score():
    """Results must be sorted by CrossEncoder score descending."""
    results = [make_result(1), make_result(2), make_result(3)]
    reranker, _ = _make_reranker_with_mock([0.4, 0.9, 0.6], threshold=0.3)

    output = reranker.rerank("query", results, top_k=10)

    assert len(output) == 3
    assert output[0].chunk_id == 2, "highest score (0.9) must be first"
    assert output[1].chunk_id == 3, "second score (0.6) must be second"
    assert output[2].chunk_id == 1, "lowest score (0.4) must be last"


def test_rerank_respects_top_k():
    """rerank() must return at most top_k results."""
    results = [make_result(i) for i in range(1, 8)]
    scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.35]
    reranker, _ = _make_reranker_with_mock(scores, threshold=0.3)

    output = reranker.rerank("query", results, top_k=3)

    assert len(output) == 3


def test_rerank_empty_input():
    """Empty input list must return empty list without calling the model."""
    reranker, mock_model = _make_reranker_with_mock([], threshold=0.3)

    output = reranker.rerank("query", [], top_k=10)

    assert output == []
    mock_model.predict.assert_not_called()


def test_rerank_score_overwritten():
    """Returned SearchResults must carry the CrossEncoder score, not the original RRF score."""
    results = [make_result(1, score=0.016), make_result(2, score=0.015)]
    reranker, _ = _make_reranker_with_mock([0.75, 0.55], threshold=0.3)

    output = reranker.rerank("query", results, top_k=10)

    assert abs(output[0].score - 0.75) < 1e-6
    assert abs(output[1].score - 0.55) < 1e-6


# ---------------------------------------------------------------------------
# SearchEngine integration with Reranker
# ---------------------------------------------------------------------------

def test_search_with_reranker_integration():
    """SearchEngine must pass fused results to reranker and return reranked output."""
    vec_results = [make_result(1), make_result(2), make_result(3)]
    bm25_results = [make_result(2), make_result(4)]

    store = MagicMock()
    store.vector_search.return_value = vec_results
    store.bm25_search.return_value = bm25_results

    provider = MagicMock()
    provider.embed.return_value = [[0.1, 0.2]]

    config = MagicMock()
    config.top_k = 5

    # Reranker mock: score chunk 3 highest, chunk 1 below threshold, rest above
    reranker = MagicMock()
    reranked = [
        make_result(3, score=0.95),
        make_result(4, score=0.80),
        make_result(2, score=0.60),
    ]
    reranker.rerank.return_value = reranked

    engine = SearchEngine(store=store, embedding_provider=provider, config=config, reranker=reranker)
    results = engine.search("test query", top_k=5)

    reranker.rerank.assert_called_once()
    call_args = reranker.rerank.call_args
    assert call_args[0][0] == "test query", "query must be passed to reranker"
    assert call_args[0][2] == 5, "top_k must be passed to reranker"

    assert len(results) == 3
    assert results[0].chunk_id == 3


def test_search_without_reranker_unchanged():
    """SearchEngine without reranker must behave identically to before (no regression)."""
    vec_results = [make_result(1), make_result(2)]
    bm25_results = [make_result(2), make_result(3)]

    store = MagicMock()
    store.vector_search.return_value = vec_results
    store.bm25_search.return_value = bm25_results

    provider = MagicMock()
    provider.embed.return_value = [[0.1, 0.2]]

    config = MagicMock()
    config.top_k = 5

    engine = SearchEngine(store=store, embedding_provider=provider, config=config)
    results = engine.search("query", top_k=3)

    assert len(results) <= 3
    # chunk 2 appears in both lists → highest RRF score → must be first
    assert results[0].chunk_id == 2
