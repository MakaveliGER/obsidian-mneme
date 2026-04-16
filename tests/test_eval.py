"""Tests for mneme.eval — load_golden_dataset, evaluate_retrieval, metrics."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mneme.eval import (
    EvalReport,
    EvalResult,
    evaluate_retrieval,
    load_golden_dataset,
    print_report,
)
from mneme.store import SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_ENTRY = {
    "question": "Was ist RAG?",
    "ground_truth_answer": "Retrieval-Augmented Generation kombiniert Suche mit LLM.",
    "expected_contexts": ["04 Ressourcen/KI/RAG"],
    "tags": ["rag"],
}


def _write_dataset(entries: list[dict]) -> Path:
    """Write a list of entries to a temp JSON file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(entries, tmp)
    tmp.close()
    return Path(tmp.name)


def _make_search_result(note_path: str, chunk_id: int = 1) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        note_path=note_path,
        note_title="Title",
        heading_path="",
        content="content",
        score=1.0,
        tags=[],
    )


def _mock_engine(results_per_query: list[list[str]]) -> MagicMock:
    """Build a mock SearchEngine that returns fixed note_paths per call."""
    engine = MagicMock()
    call_count = [0]

    def _search(query, top_k=10):
        idx = call_count[0]
        call_count[0] += 1
        paths = results_per_query[idx] if idx < len(results_per_query) else []
        return [_make_search_result(p, chunk_id=i) for i, p in enumerate(paths)]

    engine.search.side_effect = _search
    return engine


# ---------------------------------------------------------------------------
# test_load_golden_dataset
# ---------------------------------------------------------------------------

def test_load_golden_dataset_valid():
    """Valid JSON file returns a non-empty list with required keys."""
    path = _write_dataset([MINIMAL_ENTRY])
    data = load_golden_dataset(path)

    assert isinstance(data, list)
    assert len(data) == 1
    entry = data[0]
    assert "question" in entry
    assert "ground_truth_answer" in entry
    assert "expected_contexts" in entry
    assert isinstance(entry["expected_contexts"], list)


def test_load_golden_dataset_full_file():
    """The committed golden_dataset.json loads cleanly with 20 entries."""
    dataset_path = Path(__file__).parent / "golden_dataset.json"
    if not dataset_path.exists():
        pytest.skip("golden_dataset.json not found")

    data = load_golden_dataset(dataset_path)
    assert len(data) == 20
    for entry in data:
        assert entry["question"]
        assert entry["expected_contexts"]


def test_load_golden_dataset_missing_file():
    """FileNotFoundError when path does not exist."""
    with pytest.raises(FileNotFoundError):
        load_golden_dataset(Path("/nonexistent/path/dataset.json"))


def test_load_golden_dataset_invalid_json(tmp_path):
    """ValueError on malformed JSON."""
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json {{{", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_golden_dataset(bad)


def test_load_golden_dataset_not_a_list(tmp_path):
    """ValueError when root is not a JSON array."""
    p = tmp_path / "obj.json"
    p.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON array"):
        load_golden_dataset(p)


def test_load_golden_dataset_missing_key(tmp_path):
    """ValueError when an entry is missing a required key."""
    entry = {"question": "Q?", "ground_truth_answer": "A."}  # missing expected_contexts
    p = tmp_path / "incomplete.json"
    p.write_text(json.dumps([entry]), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required keys"):
        load_golden_dataset(p)


# ---------------------------------------------------------------------------
# test_eval_perfect_retrieval
# ---------------------------------------------------------------------------

def test_eval_perfect_retrieval():
    """When the engine always returns the expected context as the #1 result,
    all hit rates and MRR must equal 1.0."""
    entries = [
        {
            "question": "Frage 1",
            "ground_truth_answer": "Antwort",
            "expected_contexts": ["02 Projekte/Foo"],
            "tags": [],
        },
        {
            "question": "Frage 2",
            "ground_truth_answer": "Antwort",
            "expected_contexts": ["02 Projekte/Bar"],
            "tags": [],
        },
    ]
    # Each call returns the exact expected_context as first result
    results_per_query = [
        ["02 Projekte/Foo", "other/note.md"],
        ["02 Projekte/Bar", "other/note.md"],
    ]
    engine = _mock_engine(results_per_query)
    report = evaluate_retrieval(engine, entries, top_k=10)

    assert report.total_questions == 2
    assert report.hit_rate_at_1 == 1.0
    assert report.hit_rate_at_3 == 1.0
    assert report.hit_rate_at_10 == 1.0
    assert report.mean_mrr == 1.0


# ---------------------------------------------------------------------------
# test_eval_no_hits
# ---------------------------------------------------------------------------

def test_eval_no_hits():
    """When the engine never returns an expected context, all metrics are 0."""
    entries = [
        {
            "question": "Frage 1",
            "ground_truth_answer": "Antwort",
            "expected_contexts": ["02 Projekte/Secret"],
            "tags": [],
        },
    ]
    results_per_query = [
        ["irrelevant/note1.md", "irrelevant/note2.md"],
    ]
    engine = _mock_engine(results_per_query)
    report = evaluate_retrieval(engine, entries, top_k=10)

    assert report.hit_rate_at_1 == 0.0
    assert report.hit_rate_at_3 == 0.0
    assert report.hit_rate_at_10 == 0.0
    assert report.mean_mrr == 0.0


# ---------------------------------------------------------------------------
# test_mrr_calculation
# ---------------------------------------------------------------------------

def test_mrr_rank_1():
    """Expected context at rank 1 → MRR = 1.0."""
    entries = [{
        "question": "Q",
        "ground_truth_answer": "A",
        "expected_contexts": ["correct/note.md"],
        "tags": [],
    }]
    engine = _mock_engine([["correct/note.md", "other.md", "another.md"]])
    report = evaluate_retrieval(engine, entries, top_k=10)

    assert abs(report.mean_mrr - 1.0) < 1e-9
    assert report.results[0].mrr == pytest.approx(1.0)


def test_mrr_rank_3():
    """Expected context at rank 3 → MRR ≈ 0.333."""
    entries = [{
        "question": "Q",
        "ground_truth_answer": "A",
        "expected_contexts": ["correct/note.md"],
        "tags": [],
    }]
    engine = _mock_engine([["other1.md", "other2.md", "correct/note.md"]])
    report = evaluate_retrieval(engine, entries, top_k=10)

    assert report.results[0].mrr == pytest.approx(1 / 3, rel=1e-3)
    assert report.mean_mrr == pytest.approx(1 / 3, rel=1e-3)


def test_mrr_no_hit():
    """No expected context in results → MRR = 0.0."""
    entries = [{
        "question": "Q",
        "ground_truth_answer": "A",
        "expected_contexts": ["correct/note.md"],
        "tags": [],
    }]
    engine = _mock_engine([["wrong1.md", "wrong2.md"]])
    report = evaluate_retrieval(engine, entries, top_k=10)

    assert report.results[0].mrr == 0.0
    assert report.mean_mrr == 0.0


def test_mrr_averaged_across_questions():
    """MRR is correctly averaged: (1.0 + 0.5) / 2 = 0.75."""
    entries = [
        {
            "question": "Q1",
            "ground_truth_answer": "A",
            "expected_contexts": ["target/q1.md"],
            "tags": [],
        },
        {
            "question": "Q2",
            "ground_truth_answer": "A",
            "expected_contexts": ["target/q2.md"],
            "tags": [],
        },
    ]
    results_per_query = [
        ["target/q1.md"],       # rank 1 → 1.0
        ["other.md", "target/q2.md"],  # rank 2 → 0.5
    ]
    engine = _mock_engine(results_per_query)
    report = evaluate_retrieval(engine, entries, top_k=10)

    assert report.mean_mrr == pytest.approx(0.75, rel=1e-6)


# ---------------------------------------------------------------------------
# test_eval_report_structure
# ---------------------------------------------------------------------------

def test_eval_report_structure():
    """EvalReport contains all required fields with correct types."""
    entries = [MINIMAL_ENTRY]
    engine = _mock_engine([["04 Ressourcen/KI/RAG"]])
    report = evaluate_retrieval(engine, entries, top_k=5)

    assert isinstance(report, EvalReport)
    assert isinstance(report.total_questions, int)
    assert isinstance(report.hit_rate_at_1, float)
    assert isinstance(report.hit_rate_at_3, float)
    assert isinstance(report.hit_rate_at_10, float)
    assert isinstance(report.mean_mrr, float)
    assert isinstance(report.results, list)
    assert len(report.results) == 1

    result = report.results[0]
    assert isinstance(result, EvalResult)
    assert isinstance(result.question, str)
    assert isinstance(result.expected_contexts, list)
    assert isinstance(result.retrieved_contexts, list)
    assert isinstance(result.hit_at_1, bool)
    assert isinstance(result.hit_at_3, bool)
    assert isinstance(result.hit_at_10, bool)
    assert isinstance(result.mrr, float)


def test_eval_empty_dataset():
    """Empty dataset returns a report with zeros and no results."""
    engine = _mock_engine([])
    report = evaluate_retrieval(engine, [], top_k=10)

    assert report.total_questions == 0
    assert report.hit_rate_at_1 == 0.0
    assert report.mean_mrr == 0.0
    assert report.results == []


def test_print_report_runs_without_error(capsys):
    """print_report must produce output without raising."""
    entries = [MINIMAL_ENTRY]
    engine = _mock_engine([["04 Ressourcen/KI/RAG"]])
    report = evaluate_retrieval(engine, entries, top_k=10)
    print_report(report)

    captured = capsys.readouterr()
    assert "Hit Rate" in captured.out
    assert "MRR" in captured.out
    assert "Mneme" in captured.out


# ---------------------------------------------------------------------------
# hit-rate boundary: partial path match
# ---------------------------------------------------------------------------

def test_partial_path_match():
    """A partial substring match between expected_context and note_path counts as a hit."""
    entries = [{
        "question": "Q",
        "ground_truth_answer": "A",
        "expected_contexts": ["02 Projekte/Mneme"],
        "tags": [],
    }]
    # The retrieved path contains the expected context as a substring
    engine = _mock_engine([["02 Projekte/Mneme/Design.md"]])
    report = evaluate_retrieval(engine, entries, top_k=10)

    assert report.hit_rate_at_1 == 1.0
