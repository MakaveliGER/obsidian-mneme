"""Hybrid search (vector + BM25) with Reciprocal Rank Fusion."""

from __future__ import annotations

import logging

from mneme.store import Store, SearchResult
from mneme.embeddings.base import EmbeddingProvider
from mneme.reranker import Reranker

logger = logging.getLogger(__name__)


def rrf_fusion(
    result_lists: list[list[SearchResult]],
    weights: list[float] | None = None,
    k: int = 60,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion over multiple ranked result lists.

    RRF_score(d) = sum(weight_i * 1 / (k + rank_i(d))) for each list i where d appears.
    Identification is via chunk_id. The score field of each returned
    SearchResult is overwritten with its RRF score.

    Args:
        result_lists: Ranked result lists to fuse.
        weights: Per-list weights. Defaults to equal weighting.
        k: RRF smoothing constant (default 60).
    """
    if weights is None:
        weights = [1.0] * len(result_lists)

    rrf_scores: dict[int, float] = {}
    # Keep first-seen SearchResult object per chunk_id (carry metadata)
    best_result: dict[int, SearchResult] = {}

    for weight, result_list in zip(weights, result_lists):
        for rank, result in enumerate(result_list, start=1):
            cid = result.chunk_id
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + weight * 1.0 / (k + rank)
            if cid not in best_result:
                best_result[cid] = result

    fused: list[SearchResult] = []
    for cid, score in rrf_scores.items():
        r = best_result[cid]
        fused.append(SearchResult(
            chunk_id=r.chunk_id,
            note_path=r.note_path,
            note_title=r.note_title,
            heading_path=r.heading_path,
            content=r.content,
            score=score,
            tags=r.tags,
        ))

    fused.sort(key=lambda r: r.score, reverse=True)
    return fused


class SearchEngine:
    """Hybrid search engine combining vector and BM25 search via RRF."""

    def __init__(
        self,
        store: Store,
        embedding_provider: EmbeddingProvider,
        config,
        reranker: Reranker | None = None,
        scoring_config=None,
    ) -> None:
        # config duck-typed: needs .vector_weight, .bm25_weight, .top_k
        # scoring_config duck-typed: needs .gars_enabled, .graph_weight
        self.store = store
        self.embedding_provider = embedding_provider
        self.config = config
        self.reranker = reranker
        self.scoring_config = scoring_config
        self._centrality_map: dict[str, float] | None = None

    def _load_centrality_map(self) -> dict[str, float]:
        """Lazy-load and cache the centrality map from the store."""
        if self._centrality_map is None:
            self._centrality_map = self.store.get_centrality_map()
        return self._centrality_map

    def search(
        self,
        query: str,
        top_k: int | None = None,
        tags: list[str] | None = None,
        folders: list[str] | None = None,
        after: str | None = None,
    ) -> list[SearchResult]:
        """Hybrid search: vector + BM25, fused with RRF.

        Args:
            query: Search query text.
            top_k: Number of results. Defaults to config.top_k.
            tags: Post-filter by tags (at least one match required).
            folders: Post-filter by path prefix.
            after: Passed to BM25 pre-filter only (SearchResult has no updated_at).

        Returns:
            Top top_k results sorted by RRF score descending.
        """
        if top_k is None:
            top_k = self.config.top_k

        # Validate the `after` cutoff — SQL string-compares it against the
        # ISO-8601 `updated_at` column. Non-ISO input silently matches the
        # wrong subset, so reject early.
        if after is not None:
            from datetime import datetime
            try:
                datetime.fromisoformat(after.replace("Z", "+00:00"))
            except (ValueError, TypeError) as e:
                raise ValueError(
                    f"`after` must be an ISO-8601 date/datetime string, got {after!r}: {e}"
                ) from e

        # --- Vector search (over-retrieve, then post-filter) ---
        embedding = self.embedding_provider.embed([query])[0]
        vector_results_raw = self.store.vector_search(embedding, top_k=top_k * 3)

        vector_results: list[SearchResult] = []
        for r in vector_results_raw:
            if tags and not any(t in r.tags for t in tags):
                continue
            if folders and not any(r.note_path.startswith(f) for f in folders):
                continue
            vector_results.append(r)

        # `after` cutoff: BM25 pre-filters in SQL, vector needs a post-filter
        # because SearchResult carries no updated_at. Fetch the map in one
        # query (only when the filter is set).
        if after and vector_results:
            updated_map = self.store.get_updated_at_map(
                list({r.note_path for r in vector_results})
            )
            vector_results = [
                r for r in vector_results if updated_map.get(r.note_path, "") >= after
            ]

        # --- BM25 search (pre-filtered via SQL) ---
        bm25_results = self.store.bm25_search(
            query,
            top_k=top_k * 2,
            tags=tags,
            folders=folders,
            after=after,
        )

        # --- Fuse vector + BM25 ranks via RRF ---
        vector_w = float(getattr(self.config, "vector_weight", 0.6))
        bm25_w = float(getattr(self.config, "bm25_weight", 0.4))
        fused = rrf_fusion([vector_results, bm25_results], weights=[vector_w, bm25_w])

        if self.reranker is not None:
            # Sync GPU before CPU reranker — prevents deadlock on ROCm
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
            except Exception as e:
                logger.debug("torch.cuda.synchronize skipped: %s", e)
            results = self.reranker.rerank(query, fused, top_k)
        else:
            results = fused[:top_k]

        # --- GARS: Graph-Aware Retrieval Scoring (optional, last step) ---
        if self.scoring_config is not None and self.scoring_config.gars_enabled:
            centrality_map = self._load_centrality_map()
            graph_weight = self.scoring_config.graph_weight
            scored: list[SearchResult] = []
            for r in results:
                centrality = centrality_map.get(r.note_path, 0.0)
                final_score = (1 - graph_weight) * r.score + graph_weight * centrality
                scored.append(SearchResult(
                    chunk_id=r.chunk_id,
                    note_path=r.note_path,
                    note_title=r.note_title,
                    heading_path=r.heading_path,
                    content=r.content,
                    score=final_score,
                    tags=r.tags,
                ))
            scored.sort(key=lambda r: r.score, reverse=True)
            return scored

        return results

    def invalidate_centrality_cache(self) -> None:
        """Clear the cached centrality map. Call after index changes."""
        self._centrality_map = None

    def get_similar(self, path: str, top_k: int = 5) -> list[SearchResult]:
        """Find notes similar to the note at *path* using average chunk embedding.

        Args:
            path: Note path to find similar notes for.
            top_k: Number of similar notes to return.

        Returns:
            Top top_k results (own note excluded) sorted by similarity descending.
        """
        embeddings = self.store.get_all_chunk_embeddings_for_note(path)
        if not embeddings:
            return []

        import numpy as np
        avg_embedding = np.mean(embeddings, axis=0).tolist()

        candidates = self.store.vector_search(avg_embedding, top_k=top_k * 3)
        filtered = [r for r in candidates if r.note_path != path]
        return filtered[:top_k]
