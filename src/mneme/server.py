"""FastMCP server with 8 tools for semantic vault search."""

from __future__ import annotations

import atexit
import json
import logging
import time

from mcp.server.fastmcp import FastMCP

from mneme.config import (
    MCP_FORBIDDEN_SECTIONS,
    ConfigUpdateError,
    MnemeConfig,
    apply_config_update,
    load_config,
    save_config,
)
from mneme.embeddings import get_provider
from mneme.gardener import VaultGardener
from mneme.indexer import Indexer
from mneme.reranker import Reranker
from mneme.search import SearchEngine
from mneme.store import Store
from mneme.watcher import VaultWatcher

logger = logging.getLogger(__name__)


from mneme.paths import normalize_vault_path


def create_server(config: MnemeConfig | None = None) -> FastMCP:
    """Create and configure the Mneme MCP server with all tools."""
    if config is None:
        config = load_config()

    mcp = FastMCP("mneme", instructions="Semantic Obsidian vault search. Use search_notes to find relevant notes.")

    # Eagerly initialized at server startup — model pre-loaded so first query is fast
    state: dict = {}

    def _initialize() -> None:
        t0 = time.monotonic()
        logger.info("Mneme initializing...")

        provider = get_provider(config.embedding)

        # Pre-load the embedding model so first query doesn't block
        if hasattr(provider, "warmup"):
            provider.warmup()

        store = Store(config.db_path, provider.dimension())
        indexer = Indexer(store, provider, config)

        reranker = None
        if config.reranking.enabled:
            reranker = Reranker(
                model_name=config.reranking.model,
                threshold=config.reranking.threshold,
            )
            reranker.warmup()

        search_engine = SearchEngine(store, provider, config.search, reranker=reranker, scoring_config=config.scoring)
        gardener = VaultGardener(store, search_engine, exclude_patterns=config.health.exclude_patterns)
        state["store"] = store
        state["provider"] = provider
        state["indexer"] = indexer
        state["search"] = search_engine
        state["gardener"] = gardener
        state["config"] = config

        # Start file watcher with shutdown hook
        if config.vault.path:
            watcher = VaultWatcher(config.vault_path, indexer, config)
            watcher.start()
            state["watcher"] = watcher
            atexit.register(watcher.stop)

        logger.info("Mneme ready (%.1fs)", time.monotonic() - t0)

    # Initialize eagerly — block until model is loaded
    try:
        _initialize()
    except Exception as e:
        logger.error("Mneme initialization failed: %s", e)
        state["init_error"] = str(e)

    def _check_init() -> dict | None:
        """Return error dict if server failed to initialize, else None."""
        if "init_error" in state:
            return {"error": f"Server not initialized: {state['init_error']}"}
        if "store" not in state:
            return {"error": "Server not initialized"}
        return None

    @mcp.tool()
    def search_notes(
        query: str,
        top_k: int = 10,
        tags: list[str] | None = None,
        folders: list[str] | None = None,
        after: str | None = None,
    ) -> dict:
        """Search the Obsidian vault using hybrid semantic + keyword search.

        Args:
            query: Search query text.
            top_k: Number of results to return (default 10).
            tags: Filter by tags (at least one must match).
            folders: Filter by folder prefix (e.g. "02 Projekte/").
            after: Only include notes updated after this ISO date.

        Returns:
            Search results with path, title, content, score, and tags.
        """
        err = _check_init()
        if err:
            return err
        top_k = max(1, min(top_k, 100))
        start = time.monotonic()
        results = state["search"].search(
            query=query,
            top_k=top_k,
            tags=tags,
            folders=folders,
            after=after,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        return {
            "results": [
                {
                    "path": r.note_path,
                    "title": r.note_title,
                    "heading_path": r.heading_path,
                    "content": r.content[:1500],
                    "score": round(r.score, 4),
                    "tags": r.tags,
                }
                for r in results
            ],
            "query": query,
            "total_results": len(results),
            "search_time_ms": elapsed_ms,
        }

    @mcp.tool()
    def get_similar(path: str, top_k: int = 5) -> dict:
        """Find notes similar to a given note.

        Args:
            path: Vault-relative path of the note (e.g. "00 Kontext/Über mich.md").
            top_k: Number of similar notes to return (default 5).

        Returns:
            Similar notes with path, title, and similarity score.
        """
        err = _check_init()
        if err:
            return err
        normalized = normalize_vault_path(path)
        if normalized is None:
            return {"error": f"Invalid vault path: {path}"}
        top_k = max(1, min(top_k, 50))
        results = state["search"].get_similar(path=normalized, top_k=top_k)

        return {
            "results": [
                {
                    "path": r.note_path,
                    "title": r.note_title,
                    "score": round(r.score, 4),
                }
                for r in results
            ],
            "source_path": normalized,
            "total_results": len(results),
        }

    @mcp.tool()
    def get_note_context(path: str, depth: int = 1, similar_k: int = 3) -> dict:
        """Get a note with its graph neighbors and similar notes as a context bundle.

        Args:
            path: Vault-relative path of the note.
            depth: How many hops in the wikilink graph to traverse (default 1).
            similar_k: Number of semantically similar notes to include (default 3).

        Returns:
            Context bundle with the note, its graph neighbors, and similar notes.
        """
        err = _check_init()
        if err:
            return err
        normalized = normalize_vault_path(path)
        if normalized is None:
            return {"error": f"Invalid vault path: {path}"}
        # Allow `depth=0` (skip graph) and `similar_k=0` (skip similarity);
        # both are honest "skip this part" requests, not errors. Cap upper
        # bounds for DoS hardening.
        depth = max(0, min(depth, 3))
        similar_k = max(0, min(similar_k, 20))
        store = state["store"]
        note = store.get_note_by_path(normalized)
        if not note:
            return {"error": f"Note not found: {normalized}"}

        note_id = note["id"]

        # Graph neighbors (linked + backlinked)
        neighbors = store.get_graph_neighbors(note_id, depth=depth) if depth else []

        # Semantically similar notes
        similar = state["search"].get_similar(path=normalized, top_k=similar_k) if similar_k else []

        return {
            "note": {
                "path": note["path"],
                "title": note["title"],
                "tags": note["tags"],
                "wikilinks": note["wikilinks"],
            },
            "graph_neighbors": [
                {"path": n["path"], "title": n["title"], "direction": n["direction"]}
                for n in neighbors
            ],
            "similar_notes": [
                {"path": r.note_path, "title": r.note_title, "score": round(r.score, 4)}
                for r in similar
            ],
            "total_neighbors": len(neighbors),
            "total_similar": len(similar),
        }

    @mcp.tool()
    def vault_stats() -> dict:
        """Get index statistics — total notes, chunks, last indexed, DB size.

        Returns:
            Index statistics including note count, chunk count, and database size.
        """
        err = _check_init()
        if err:
            return err
        stats = state["store"].get_stats(
            embedding_model=state["config"].embedding.model
        )
        return {
            "total_notes": stats.total_notes,
            "total_chunks": stats.total_chunks,
            "last_indexed": stats.last_indexed,
            "embedding_model": stats.embedding_model,
            "db_size_mb": stats.db_size_mb,
        }

    @mcp.tool()
    def reindex(full: bool = False) -> dict:
        """Re-index the vault. Incremental by default (only changed files).

        Args:
            full: If True, re-index all notes regardless of changes.

        Returns:
            Indexing results with counts of indexed, skipped, and deleted notes.
        """
        err = _check_init()
        if err:
            return err
        result = state["indexer"].index_vault(full=full)
        # Invalidate centrality cache after reindex (graph may have changed)
        state["search"].invalidate_centrality_cache()
        return {
            "indexed": result.indexed,
            "skipped": result.skipped,
            "deleted": result.deleted,
            "duration_seconds": round(result.duration_seconds, 2),
        }

    @mcp.tool()
    def get_config() -> dict:
        """Get the current Mneme configuration.

        Paths (vault, database) are redacted to booleans so this tool can't
        be used for prompt-injection-driven PII exfiltration. Use the CLI
        (`mneme get-config`) if you need the real paths.

        Returns:
            Current configuration as a dictionary.
        """
        err = _check_init()
        if err:
            return err
        data = state["config"].model_dump()
        # Redact anything path-like that would leak local filesystem layout.
        if "vault" in data and isinstance(data["vault"], dict):
            data["vault"]["path"] = "<set>" if data["vault"].get("path") else "<unset>"
        if "database" in data and isinstance(data["database"], dict):
            data["database"]["path"] = "<set>" if data["database"].get("path") else "<unset>"
        return data

    @mcp.tool()
    def update_config(key: str, value: str) -> dict:
        """Update a configuration setting. Use dot-notation for nested keys.

        Args:
            key: Config key in dot-notation (e.g. "search.top_k").
            value: New value as string (will be parsed to appropriate type).

        Returns:
            Updated key with old and new values. Note: some changes require restart.
        """
        err = _check_init()
        if err:
            return err
        section_name = key.split(".", 1)[0]
        if section_name in MCP_FORBIDDEN_SECTIONS:
            return {
                "error": (
                    f"Section '{section_name}' cannot be modified via MCP. "
                    f"Use `mneme update-config {key} <value>` on the CLI."
                )
            }

        cfg = state["config"]
        try:
            _, old_value, parsed = apply_config_update(cfg, key, value)
        except ConfigUpdateError as e:
            return {"error": str(e)}

        save_config(cfg)

        return {
            "updated_key": key,
            "old_value": str(old_value),
            "new_value": str(parsed),
        }

    @mcp.tool()
    def vault_health(
        stale_days: int = 30,
        similarity_threshold: float = 0.85,
        checks: list[str] | None = None,
    ) -> dict:
        """Analyze vault health — find orphans, weak links, stale notes, near-duplicates.

        Args:
            stale_days: Notes with status 'aktiv' unchanged for this many days are stale.
            similarity_threshold: Notes with similarity above this are potential duplicates.
            checks: List of checks to run. Default: all.
                    Options: orphans, weak_links, stale, duplicates.

        Returns:
            Health report with results for each requested check.
        """
        err = _check_init()
        if err:
            return err
        gardener: VaultGardener = state["gardener"]
        all_checks = checks is None

        report: dict = {}

        if all_checks or "orphans" in checks:
            report["orphan_pages"] = gardener.find_orphans()

        if all_checks or "weak_links" in checks:
            report["weakly_linked"] = gardener.find_weakly_linked(top_k=10)

        if all_checks or "stale" in checks:
            report["stale_notes"] = gardener.find_stale_notes(days=stale_days)

        if all_checks or "duplicates" in checks:
            report["near_duplicates"] = gardener.find_near_duplicates(threshold=similarity_threshold)

        return report

    # ------------------------------------------------------------------
    # MCP Resources — static vault metadata without tool-call overhead
    # ------------------------------------------------------------------

    @mcp.resource("mneme://vault/stats")
    def vault_stats_resource() -> str:
        """Current vault index statistics."""
        stats = state["store"].get_stats(embedding_model=state["config"].embedding.model)
        return json.dumps({
            "total_notes": stats.total_notes,
            "total_chunks": stats.total_chunks,
            "last_indexed": stats.last_indexed,
            "embedding_model": stats.embedding_model,
            "db_size_mb": stats.db_size_mb,
        }, indent=2)

    @mcp.resource("mneme://vault/tags")
    def vault_tags_resource() -> str:
        """List of all unique tags in the vault."""
        rows = state["store"]._conn.execute(
            "SELECT DISTINCT tags FROM notes WHERE tags != '[]'"
        ).fetchall()
        all_tags: set[str] = set()
        for row in rows:
            tags = json.loads(row[0])
            all_tags.update(tags)
        return json.dumps(sorted(all_tags), indent=2)

    @mcp.resource("mneme://vault/graph-summary")
    def vault_graph_resource() -> str:
        """Wikilink graph summary — most connected notes."""
        centrality = state["store"].get_centrality_map()
        top_10 = sorted(centrality.items(), key=lambda x: x[1], reverse=True)[:10]
        return json.dumps([
            {"path": path, "centrality": round(score, 3)}
            for path, score in top_10
        ], indent=2)

    # ------------------------------------------------------------------
    # MCP Prompts — predefined workflow templates
    # ------------------------------------------------------------------

    @mcp.prompt()
    def research_topic(topic: str) -> str:
        """Research a topic using vault knowledge. Searches for relevant notes and synthesizes findings."""
        return f"""Recherchiere das Thema "{topic}" in meinem Vault.

1. Nutze search_notes um relevante Notizen zu finden
2. Nutze get_note_context für die wichtigsten Treffer um den Kontext zu verstehen
3. Fasse zusammen: Was weiß mein Vault über dieses Thema?
4. Identifiziere Wissenslücken: Was fehlt noch?"""

    @mcp.prompt()
    def vault_review() -> str:
        """Run a comprehensive vault health check and suggest improvements."""
        return """Führe einen Vault-Health-Check durch:

1. Nutze vault_health um Probleme zu finden (Orphans, schwache Links, veraltete Notizen)
2. Für die Top-3 Orphan-Notes: Nutze get_similar um Verlinkungsvorschläge zu machen
3. Erstelle einen Bericht mit konkreten Handlungsempfehlungen"""

    @mcp.prompt()
    def find_connections(note_path: str) -> str:
        """Discover hidden connections for a specific note."""
        return f"""Finde versteckte Verbindungen für die Notiz "{note_path}":

1. Nutze get_note_context um bestehende Verbindungen zu sehen
2. Nutze search_notes mit Schlüsselwörtern aus der Notiz um verwandte Inhalte zu finden
3. Vergleiche: Welche semantisch ähnlichen Notizen sind NICHT verlinkt?
4. Schlage konkrete [[Wikilinks]] vor die hinzugefügt werden sollten"""

    return mcp
