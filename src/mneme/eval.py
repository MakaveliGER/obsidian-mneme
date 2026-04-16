"""Mneme retrieval evaluation using custom metrics (Hit Rate + MRR)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass
class EvalResult:
    question: str
    expected_contexts: list[str]
    retrieved_contexts: list[str]
    hit_at_1: bool   # Expected context in top-1?
    hit_at_3: bool   # Expected context in top-3?
    hit_at_10: bool  # Expected context in top-10?
    mrr: float       # Reciprocal Rank for this question (0.0 if no hit)


@dataclass
class EvalReport:
    total_questions: int
    hit_rate_at_1: float   # Fraction of questions where expected in top-1
    hit_rate_at_3: float   # Fraction of questions where expected in top-3
    hit_rate_at_10: float  # Fraction of questions where expected in top-10
    mean_mrr: float        # Average MRR across all questions
    results: list[EvalResult]


def load_golden_dataset(path: Path) -> list[dict]:
    """Load and return the golden dataset from a JSON file.

    Args:
        path: Path to the golden dataset JSON file.

    Returns:
        List of dataset entries, each with 'question', 'ground_truth_answer',
        'expected_contexts', and 'tags' keys.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the JSON is malformed or required keys are missing.
    """
    if not path.exists():
        raise FileNotFoundError(f"Golden dataset not found: {path}")

    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in golden dataset: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("Golden dataset must be a JSON array")

    required_keys = {"question", "ground_truth_answer", "expected_contexts"}
    for i, entry in enumerate(data):
        missing = required_keys - set(entry.keys())
        if missing:
            raise ValueError(
                f"Entry {i} is missing required keys: {missing}"
            )
        if not isinstance(entry["expected_contexts"], list):
            raise ValueError(
                f"Entry {i}: 'expected_contexts' must be a list"
            )

    return data


def _compute_mrr(expected: list[str], retrieved: list[str]) -> float:
    """Compute the Reciprocal Rank for one question.

    Returns 1/rank of the first retrieved context that partially matches
    any expected context string. Returns 0.0 if no match.
    """
    for rank, ctx in enumerate(retrieved, start=1):
        for exp in expected:
            # Partial match: expected_context is a substring of the note_path
            if exp in ctx or ctx in exp:
                return 1.0 / rank
    return 0.0


def _has_hit(expected: list[str], retrieved: list[str], top_k: int) -> bool:
    """Return True if any expected context appears in the top_k retrieved."""
    subset = retrieved[:top_k]
    for ctx in subset:
        for exp in expected:
            if exp in ctx or ctx in exp:
                return True
    return False


def evaluate_retrieval(
    search_engine,
    dataset: list[dict],
    top_k: int = 10,
) -> EvalReport:
    """Evaluate retrieval quality against a golden dataset.

    For each question in the dataset the search engine is queried. The
    retrieved note_paths are compared against the expected_contexts (partial
    match: expected string is a substring of the note_path or vice versa).

    Args:
        search_engine: A ``SearchEngine`` instance (or compatible mock) with a
            ``search(query, top_k) -> list[SearchResult]`` method.
        dataset: List of dataset entries as returned by ``load_golden_dataset``.
        top_k: How many results to retrieve per question.

    Returns:
        An ``EvalReport`` with aggregated metrics and per-question results.
    """
    results: list[EvalResult] = []

    for entry in dataset:
        question: str = entry["question"]
        expected: list[str] = entry["expected_contexts"]

        search_results = search_engine.search(question, top_k=top_k)
        retrieved_paths = [r.note_path for r in search_results]

        hit1 = _has_hit(expected, retrieved_paths, top_k=1)
        hit3 = _has_hit(expected, retrieved_paths, top_k=3)
        hit10 = _has_hit(expected, retrieved_paths, top_k=10)
        mrr = _compute_mrr(expected, retrieved_paths)

        results.append(EvalResult(
            question=question,
            expected_contexts=expected,
            retrieved_contexts=retrieved_paths,
            hit_at_1=hit1,
            hit_at_3=hit3,
            hit_at_10=hit10,
            mrr=mrr,
        ))

    n = len(results)
    if n == 0:
        return EvalReport(
            total_questions=0,
            hit_rate_at_1=0.0,
            hit_rate_at_3=0.0,
            hit_rate_at_10=0.0,
            mean_mrr=0.0,
            results=[],
        )

    return EvalReport(
        total_questions=n,
        hit_rate_at_1=sum(r.hit_at_1 for r in results) / n,
        hit_rate_at_3=sum(r.hit_at_3 for r in results) / n,
        hit_rate_at_10=sum(r.hit_at_10 for r in results) / n,
        mean_mrr=sum(r.mrr for r in results) / n,
        results=results,
    )


def print_report(report: EvalReport) -> None:
    """Print a formatted evaluation report to stdout."""
    print("=" * 60)
    print("Mneme Retrieval Evaluation Report")
    print("=" * 60)
    print(f"  Questions evaluated : {report.total_questions}")
    print(f"  Hit Rate @1         : {report.hit_rate_at_1:.1%}")
    print(f"  Hit Rate @3         : {report.hit_rate_at_3:.1%}")
    print(f"  Hit Rate @10        : {report.hit_rate_at_10:.1%}")
    print(f"  Mean MRR            : {report.mean_mrr:.4f}")
    print()
    print("Per-question breakdown:")
    print("-" * 60)
    for i, r in enumerate(report.results, start=1):
        hit_symbol = (
            "@1" if r.hit_at_1 else
            "@3" if r.hit_at_3 else
            "@10" if r.hit_at_10 else
            "MISS"
        )
        mrr_str = f"MRR={r.mrr:.2f}" if r.mrr > 0 else "MRR=0"
        question_short = r.question[:55] + "..." if len(r.question) > 58 else r.question
        print(f"  [{i:2d}] {hit_symbol:<4}  {mrr_str}  {question_short}")
    print("=" * 60)
