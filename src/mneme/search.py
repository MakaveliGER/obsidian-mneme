"""Hybrid search (vector + BM25) with Reciprocal Rank Fusion."""

from __future__ import annotations

import logging
import re

from mneme.store import Store, SearchResult
from mneme.embeddings.base import EmbeddingProvider
from mneme.reranker import Reranker

logger = logging.getLogger(__name__)


# Strips the `[Title: ... | Folder: ... | Tags: ...]` context header that the
# parser prepends to every chunk. It's indexing metadata for the LLM context,
# not something a user wants to read in a preview snippet — and at ~60-80
# chars it eats a third of the 200-char budget.
_CONTEXT_HEADER_RE = re.compile(r"^\s*\[Title:[^\]]*\]\s*")


def diversify_by_file(
    results: list[SearchResult], max_per_file: int = 2
) -> list[SearchResult]:
    """Cap how many chunks from the same note can appear in the output.

    Preserves input order (so the best-ranked chunks per file survive the
    cap). Prevents a single large note from dominating top-k when it has
    many chunks that score well — the live test showed a 70-page research
    doc filling 4 of 5 slots, pushing out the dedicated domain notes.

    Call site: after RRF fusion, before the top_k slice / reranker pass.
    """
    seen: dict[str, int] = {}
    out: list[SearchResult] = []
    for r in results:
        count = seen.get(r.note_path, 0)
        if count < max_per_file:
            out.append(r)
            seen[r.note_path] = count + 1
    return out


def clean_snippet(text: str, max_chars: int = 200) -> str:
    """Produce a readable preview snippet from chunk content.

    Strips noise that's unhelpful in an LLM context window or a search-UI
    preview: fenced code blocks, markdown tables, repeated whitespace.
    Truncates cleanly at a sentence boundary when one is close to the
    char limit; otherwise cuts and appends an ellipsis.
    """
    if not text:
        return ""
    # Strip the chunker's context header before anything else — otherwise it
    # eats the budget and leaks indexing metadata into the user-facing preview.
    text = _CONTEXT_HEADER_RE.sub("", text, count=1)
    # Fenced code blocks — rarely the right thing to show as a preview
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Table rows: lines with 3+ pipes are almost always markdown tables
    text = "\n".join(line for line in text.splitlines() if line.count("|") < 3)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # Prefer cutting at a sentence boundary if one falls in the back 40%
    # of the cut — otherwise the ellipsis mid-sentence is fine.
    last_period = cut.rfind(". ")
    if last_period > max_chars * 0.6:
        return cut[: last_period + 1]
    return cut.rstrip() + "…"


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

        # Diversify by file BEFORE slicing to top_k — prevents a large note
        # with many relevant chunks (e.g. a 70-page research doc) from filling
        # the top-k output and pushing dedicated domain notes out. Applied
        # also as input to the reranker so the reranker sees a diverse
        # candidate pool.
        fused = diversify_by_file(fused, max_per_file=2)

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

        # Over-retrieve enough to survive filtering out *this* note's own
        # chunks AND to have headroom after per-note deduplication. A note
        # with N chunks can fill up to N slots in the vector search before
        # the path filter runs; after filtering, multiple chunks from the
        # same neighbour collapse to one entry. Without deduplication,
        # callers (Gardener weak_links, MCP get_similar tool) got the
        # same note listed N times with different chunk scores.
        n_own_chunks = len(embeddings)
        candidates = self.store.vector_search(
            avg_embedding, top_k=n_own_chunks + (top_k * 3) + 10
        )

        # Deduplicate by note_path, keeping the highest-scoring chunk per
        # note. Results are sorted by score descending (best-first) before
        # the top_k slice.
        best_by_path: dict[str, SearchResult] = {}
        for r in candidates:
            if r.note_path == path:
                continue
            existing = best_by_path.get(r.note_path)
            if existing is None or r.score > existing.score:
                best_by_path[r.note_path] = r
        deduped = sorted(best_by_path.values(), key=lambda r: r.score, reverse=True)
        return deduped[:top_k]
