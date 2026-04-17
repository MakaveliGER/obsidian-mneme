"""CrossEncoder Reranker for post-fusion result reranking."""

from __future__ import annotations

import logging
import time

# Apply the torch.distributed shim before sentence-transformers is imported.
from mneme import _torch_compat  # noqa: F401
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

            import torch
            from sentence_transformers import CrossEncoder

            # Use GPU if available — single predict works on ROCm,
            # batch predict hangs (handled in rerank() below).
            device = "cpu"
            if torch.cuda.is_available():
                device = "cuda"

            self._model = CrossEncoder(self.model_name, device=device)

            # Warmup predict — first call triggers kernel init
            self._model.predict([("warmup", "warmup")], show_progress_bar=False)
            logger.info("Reranker loaded on %s in %.1fs", device, time.monotonic() - t0)
        return self._model

    def warmup(self):
        self._load_model()

    def rerank(self, query: str, results: list[SearchResult], top_k: int) -> list[SearchResult]:
        """Rerank results using CrossEncoder. Filter by threshold. Return top_k."""
        if not results:
            return []

        model = self._load_model()

        # Limit candidates and truncate content for performance.
        # CrossEncoder max seq length is 512 tokens (~2000 chars).
        # Scoring 50+ full chunks on CPU would take minutes.
        max_candidates = min(len(results), top_k * 3)
        candidates = results[:max_candidates]
        pairs = [(query, r.content[:2000]) for r in candidates]

        # Score pairs one by one — batch predict hangs on ROCm Windows
        raw_scores = [
            float(model.predict([pair], show_progress_bar=False)[0])
            for pair in pairs
        ]

        # Normalize scores to [0, 1] via sigmoid (CrossEncoder returns logits)
        import math
        scores = [1.0 / (1.0 + math.exp(-float(s))) for s in raw_scores]

        # Attach scores and filter
        scored = []
        for result, score in zip(candidates, scores):
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
