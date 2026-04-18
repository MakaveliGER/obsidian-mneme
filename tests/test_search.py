"""Tests for mneme.search — rrf_fusion and SearchEngine."""

from __future__ import annotations

from unittest.mock import MagicMock

from mneme.store import SearchResult
from mneme.search import rrf_fusion, SearchEngine, diversify_by_file, clean_snippet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_result(chunk_id: int, note_path: str = "note.md", score: float = 1.0) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        note_path=note_path,
        note_title="Title",
        heading_path="",
        content="content",
        score=score,
        tags=[],
    )


# ---------------------------------------------------------------------------
# rrf_fusion tests
# ---------------------------------------------------------------------------

def test_rrf_fusion_both_lists():
    """A chunk that appears in both lists must receive a higher RRF score
    than a chunk that appears in only one list."""
    shared = make_result(chunk_id=1)
    only_vector = make_result(chunk_id=2)
    only_bm25 = make_result(chunk_id=3)

    vector_list = [shared, only_vector]
    bm25_list = [shared, only_bm25]

    fused = rrf_fusion([vector_list, bm25_list])

    scores = {r.chunk_id: r.score for r in fused}
    assert scores[1] > scores[2], "shared chunk must outscore vector-only chunk"
    assert scores[1] > scores[3], "shared chunk must outscore bm25-only chunk"


def test_rrf_fusion_order():
    """Results must be sorted by RRF score descending."""
    r1 = make_result(chunk_id=1)
    r2 = make_result(chunk_id=2)
    r3 = make_result(chunk_id=3)

    list_a = [r1, r2]
    list_b = [r1, r3]

    fused = rrf_fusion([list_a, list_b])

    assert fused[0].chunk_id == 1, "highest-scoring chunk must be first"
    for i in range(len(fused) - 1):
        assert fused[i].score >= fused[i + 1].score, "scores must be non-increasing"


def test_rrf_fusion_empty_lists():
    """Empty input → empty output."""
    assert rrf_fusion([]) == []
    assert rrf_fusion([[], []]) == []


def test_rrf_fusion_single_list():
    """Single list → RRF scores reflect rank order (rank 1 > rank 2 > …)."""
    results = [make_result(i) for i in range(1, 5)]
    fused = rrf_fusion([results])

    assert len(fused) == 4
    for i in range(len(fused) - 1):
        assert fused[i].score > fused[i + 1].score, (
            f"rank {i+1} score must be greater than rank {i+2} score"
        )
    expected_first = 1.0 / (60 + 1)
    assert abs(fused[0].score - expected_first) < 1e-9


# ---------------------------------------------------------------------------
# SearchEngine tests
# ---------------------------------------------------------------------------

def _make_engine(vector_results=None, bm25_results=None, top_k=5):
    """Build a SearchEngine backed by mocked Store and EmbeddingProvider."""
    store = MagicMock()
    store.vector_search.return_value = vector_results or []
    store.bm25_search.return_value = bm25_results or []

    provider = MagicMock()
    provider.embed.return_value = [[0.1, 0.2, 0.3]]

    config = MagicMock()
    config.top_k = top_k

    return SearchEngine(store=store, embedding_provider=provider, config=config)


def test_search_end_to_end():
    """search() must call both vector_search and bm25_search and return results."""
    vec_results = [make_result(1), make_result(2)]
    bm25_results = [make_result(2), make_result(3)]

    engine = _make_engine(vector_results=vec_results, bm25_results=bm25_results)
    results = engine.search("test query")

    assert len(results) > 0, "search must return at least one result"
    assert results[0].chunk_id == 2

    engine.store.vector_search.assert_called_once()
    engine.store.bm25_search.assert_called_once()
    engine.embedding_provider.embed.assert_called_once_with(["test query"])


def test_search_respects_top_k():
    """search() must return at most top_k results."""
    vec_results = [make_result(i) for i in range(1, 11)]
    bm25_results = [make_result(i) for i in range(6, 16)]

    engine = _make_engine(vector_results=vec_results, bm25_results=bm25_results, top_k=4)
    results = engine.search("query", top_k=4)

    assert len(results) <= 4


def test_search_tag_postfilter():
    """Vector results without matching tags must be filtered out."""
    tagged = SearchResult(
        chunk_id=1, note_path="a.md", note_title="A",
        heading_path="", content="x", score=1.0, tags=["python"],
    )
    untagged = SearchResult(
        chunk_id=2, note_path="b.md", note_title="B",
        heading_path="", content="y", score=0.9, tags=["java"],
    )

    engine = _make_engine(vector_results=[tagged, untagged], bm25_results=[])
    results = engine.search("query", tags=["python"])

    chunk_ids = {r.chunk_id for r in results}
    assert 1 in chunk_ids, "tagged result must survive post-filter"
    assert 2 not in chunk_ids, "untagged result must be filtered out"


def test_search_folder_postfilter():
    """Vector results not matching any folder prefix must be filtered out."""
    in_folder = make_result(chunk_id=10, note_path="projects/foo.md")
    out_folder = make_result(chunk_id=11, note_path="archive/bar.md")

    engine = _make_engine(vector_results=[in_folder, out_folder], bm25_results=[])
    results = engine.search("query", folders=["projects/"])

    chunk_ids = {r.chunk_id for r in results}
    assert 10 in chunk_ids
    assert 11 not in chunk_ids


# ---------------------------------------------------------------------------
# get_similar tests
# ---------------------------------------------------------------------------

def test_get_similar_filters_own_note():
    """get_similar must exclude the queried note from results."""
    own_path = "notes/target.md"
    own_result = make_result(chunk_id=99, note_path=own_path)
    other_result = make_result(chunk_id=1, note_path="notes/other.md")

    store = MagicMock()
    store.get_all_chunk_embeddings_for_note.return_value = [
        [1.0, 0.0],
        [0.0, 1.0],
    ]
    store.vector_search.return_value = [own_result, other_result]

    provider = MagicMock()
    config = MagicMock()
    config.top_k = 5

    engine = SearchEngine(store=store, embedding_provider=provider, config=config)
    results = engine.get_similar(own_path, top_k=5)

    paths = {r.note_path for r in results}
    assert own_path not in paths, "own note must be filtered from get_similar results"
    assert "notes/other.md" in paths


def test_get_similar_empty_when_no_embeddings():
    """get_similar must return [] when no chunks exist for the path."""
    store = MagicMock()
    store.get_all_chunk_embeddings_for_note.return_value = []

    engine = SearchEngine(
        store=store,
        embedding_provider=MagicMock(),
        config=MagicMock(),
    )
    assert engine.get_similar("nonexistent.md") == []
    store.vector_search.assert_not_called()


def test_get_similar_over_retrieves_beyond_own_chunks():
    """Regression: large notes must not empty the result list.

    A note with many chunks can fill up to N slots in the vector-search top.
    The over-retrieval factor must take n_own_chunks into account so the
    path filter doesn't leave filtered[] empty."""
    own_path = "notes/big_note.md"
    # 20 own chunks — previously top_k * 3 = 9 or 15 candidates would all
    # be own chunks, leaving zero after path-filter.
    own_embeddings = [[1.0, 0.0]] * 20
    store = MagicMock()
    store.get_all_chunk_embeddings_for_note.return_value = own_embeddings

    # Simulate vector_search returning own chunks first, then one other note.
    own_hits = [make_result(chunk_id=i, note_path=own_path) for i in range(20)]
    other_hits = [make_result(chunk_id=100, note_path="notes/other.md", score=0.7)]
    store.vector_search.return_value = own_hits + other_hits

    engine = SearchEngine(
        store=store,
        embedding_provider=MagicMock(),
        config=MagicMock(),
    )
    results = engine.get_similar(own_path, top_k=3)

    # Verify over-retrieval factor scales with n_own_chunks.
    call_kwargs = store.vector_search.call_args.kwargs
    assert call_kwargs["top_k"] > 20, (
        "over-retrieval must exceed the number of own chunks; "
        f"got top_k={call_kwargs['top_k']}"
    )
    assert len(results) == 1
    assert results[0].note_path == "notes/other.md"


def test_get_similar_deduplicates_by_note_path():
    """get_similar must collapse multiple chunks of the same note into one
    entry, keeping the highest-scoring chunk. Previously callers like
    Gardener.find_weakly_linked() got the same note N times."""
    own_path = "notes/query.md"
    store = MagicMock()
    store.get_all_chunk_embeddings_for_note.return_value = [[1.0, 0.0]]

    # Three chunks from the same neighbour note, plus one from a different
    # neighbour. Dedup must keep the highest score per note.
    store.vector_search.return_value = [
        make_result(chunk_id=1, note_path="notes/alpha.md", score=0.9),
        make_result(chunk_id=2, note_path="notes/alpha.md", score=0.7),
        make_result(chunk_id=3, note_path="notes/alpha.md", score=0.5),
        make_result(chunk_id=4, note_path="notes/beta.md", score=0.6),
    ]

    engine = SearchEngine(
        store=store,
        embedding_provider=MagicMock(),
        config=MagicMock(),
    )
    results = engine.get_similar(own_path, top_k=10)

    paths = [r.note_path for r in results]
    assert paths == ["notes/alpha.md", "notes/beta.md"], (
        f"expected deduplicated, score-sorted paths; got {paths}"
    )
    alpha = next(r for r in results if r.note_path == "notes/alpha.md")
    assert alpha.score == 0.9, "must keep highest-scoring chunk per note"


# ---------------------------------------------------------------------------
# diversify_by_file tests
# ---------------------------------------------------------------------------

def test_diversify_by_file_caps_per_note():
    """Same-file chunks beyond max_per_file are dropped while order is kept."""
    results = [
        make_result(1, "big.md", score=0.9),
        make_result(2, "big.md", score=0.8),
        make_result(3, "big.md", score=0.7),
        make_result(4, "big.md", score=0.6),   # must be dropped
        make_result(5, "other.md", score=0.5),
        make_result(6, "big.md", score=0.4),   # must be dropped too
    ]
    out = diversify_by_file(results, max_per_file=3)

    paths = [r.note_path for r in out]
    assert paths == ["big.md", "big.md", "big.md", "other.md"]
    # best-scoring chunks from big.md survive (order preserved)
    big_scores = [r.score for r in out if r.note_path == "big.md"]
    assert big_scores == [0.9, 0.8, 0.7]


def test_diversify_by_file_preserves_diverse_input():
    """When no file exceeds max_per_file, nothing changes."""
    results = [
        make_result(1, "a.md"),
        make_result(2, "b.md"),
        make_result(3, "c.md"),
    ]
    assert diversify_by_file(results, max_per_file=3) == results


def test_diversify_by_file_empty_input():
    assert diversify_by_file([], max_per_file=3) == []


# ---------------------------------------------------------------------------
# clean_snippet tests
# ---------------------------------------------------------------------------

def test_clean_snippet_strips_fenced_code_blocks():
    text = "Intro before code.\n```python\ndef foo():\n    return 42\n```\nMore prose after."
    out = clean_snippet(text, max_chars=200)
    assert "def foo" not in out
    assert "return 42" not in out
    assert "Intro before code" in out
    assert "More prose after" in out


def test_clean_snippet_strips_markdown_tables():
    text = "Heading context.\n| col1 | col2 | col3 |\n|------|------|------|\n| a | b | c |\nAfter the table."
    out = clean_snippet(text, max_chars=200)
    assert "col1" not in out
    assert "|" not in out
    assert "Heading context" in out
    assert "After the table" in out


def test_clean_snippet_truncates_at_sentence_boundary_when_possible():
    # First sentence is 46 chars — well past the 60% mark of max_chars=50,
    # so the snippet should cut at the sentence boundary instead of adding
    # an ellipsis mid-word.
    text = "This is a long sentence filling the budget. Rest is discarded entirely."
    out = clean_snippet(text, max_chars=50)
    assert out.endswith(".")
    assert len(out) <= 50


def test_clean_snippet_falls_back_to_ellipsis_for_early_sentence_breaks():
    # Sentence break at char 15 — only 30% through a 50-char budget. Cutting
    # there would waste too much capacity, so ellipsis-cut is preferred.
    text = "Short intro. Much longer second sentence continues way past the cut mark here."
    out = clean_snippet(text, max_chars=50)
    assert out.endswith("…")
    assert len(out) <= 51  # +1 for the ellipsis character


def test_clean_snippet_ellipsis_when_no_sentence_break():
    text = "A very long word-chain without punctuation that just keeps going endlessly and endlessly"
    out = clean_snippet(text, max_chars=30)
    assert out.endswith("…")
    # ellipsis accounts for extra char, so length ≤ max+1
    assert len(out) <= 31


def test_clean_snippet_collapses_whitespace():
    text = "Multiple   spaces\n\n\nand\tnewlines   collapse"
    out = clean_snippet(text, max_chars=200)
    assert "   " not in out
    assert "\n" not in out


def test_clean_snippet_empty_input():
    assert clean_snippet("", max_chars=200) == ""
    assert clean_snippet(None, max_chars=200) == ""  # type: ignore[arg-type]
