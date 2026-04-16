"""CrossEncoder Reranker for post-fusion result reranking."""

from __future__ import annotations

import logging
import time

from mneme.store import SearchResult

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self, model_name: str, threshold: float = 0.3):
        self.model_name = model_name
        self.threshold = threshold
        self._model = None

    def _load_model(self):
        if self._model is None:
            logger.info("Loading reranker model: %s", self.model_name)
            t0 = time.monotonic()
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
            logger.info("Reranker loaded in %.1fs", time.monotonic() - t0)
        return self._model

    def warmup(self):
        self._load_model()

    def rerank(self, query: str, results: list[SearchResult], top_k: int) -> list[SearchResult]:
        """Rerank results using CrossEncoder. Filter by threshold. Return top_k."""
        if not results:
            return []

        model = self._load_model()

        # Prepare pairs for CrossEncoder
        pairs = [(query, r.content) for r in results]

        # Score all pairs
        scores = model.predict(pairs, show_progress_bar=False)

        # Attach scores and filter
        scored = []
        for result, score in zip(results, scores):
            if score >= self.threshold:
                scored.append(SearchResult(
                    chunk_id=result.chunk_id,
                    note_path=result.note_path,
                    note_title=result.note_title,
                    heading_path=result.heading_path,
                    content=result.content,
                    score=float(score),
                    tags=result.tags,
                ))

        # Sort by reranker score descending
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]
