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

            # Patch torch.distributed for ROCm Windows
            # (module exists but is_initialized/get_rank are missing)
            import torch
            if not hasattr(torch, "distributed"):
                class _DummyDistributed:
                    pass
                torch.distributed = _DummyDistributed()
            if not hasattr(torch.distributed, "is_initialized"):
                torch.distributed.is_initialized = lambda: False
            if not hasattr(torch.distributed, "get_rank"):
                torch.distributed.get_rank = lambda: 0

            from sentence_transformers import CrossEncoder

            # Detect device — use GPU if available
            device = "cpu"
            if torch.cuda.is_available():
                device = "cuda"

            self._model = CrossEncoder(self.model_name, device=device)
            logger.info("Reranker loaded on cpu in %.1fs", time.monotonic() - t0)
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
        raw_scores = model.predict(pairs, show_progress_bar=False)

        # Normalize scores to [0, 1] via sigmoid (CrossEncoder returns logits)
        import math
        scores = [1.0 / (1.0 + math.exp(-float(s))) for s in raw_scores]

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
                    score=score,
                    tags=result.tags,
                ))

        # Sort by reranker score descending
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]
