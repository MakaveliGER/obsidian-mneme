"""FastMCP server with 6 tools for semantic vault search."""

from __future__ import annotations

import logging
import time

from mcp.server.fastmcp import FastMCP

from mneme.config import MnemeConfig, load_config, save_config
from mneme.embeddings import get_provider
from mneme.indexer import Indexer
from mneme.search import SearchEngine
from mneme.store import Store
from mneme.watcher import VaultWatcher

logger = logging.getLogger(__name__)


def create_server(config: MnemeConfig | None = None) -> FastMCP:
    """Create and configure the Mneme MCP server with all tools."""
    if config is None:
        config = load_config()

    mcp = FastMCP("mneme", instructions="Semantic Obsidian vault search. Use search_notes to find relevant notes.")

    # Lazy-initialized components (first tool call triggers init)
    state: dict = {}

    def _ensure_initialized() -> None:
        if "store" in state:
            return
        provider = get_provider(config.embedding)
        store = Store(config.db_path, provider.dimension())
        indexer = Indexer(store, provider, config)
        search_engine = SearchEngine(store, provider, config.search)
        state["store"] = store
        state["provider"] = provider
        state["indexer"] = indexer
        state["search"] = search_engine
        state["config"] = config

        # Start file watcher
        if config.vault.path:
            watcher = VaultWatcher(config.vault_path, indexer, config)
            watcher.start()
            state["watcher"] = watcher

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
        _ensure_initialized()
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
        _ensure_initialized()
        results = state["search"].get_similar(path=path, top_k=top_k)

        return {
            "results": [
                {
                    "path": r.note_path,
                    "title": r.note_title,
                    "score": round(r.score, 4),
                }
                for r in results
            ],
            "source_path": path,
            "total_results": len(results),
        }

    @mcp.tool()
    def vault_stats() -> dict:
        """Get index statistics — total notes, chunks, last indexed, DB size.

        Returns:
            Index statistics including note count, chunk count, and database size.
        """
        _ensure_initialized()
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
        _ensure_initialized()
        result = state["indexer"].index_vault(full=full)
        return {
            "indexed": result.indexed,
            "skipped": result.skipped,
            "deleted": result.deleted,
            "duration_seconds": round(result.duration_seconds, 2),
        }

    @mcp.tool()
    def get_config() -> dict:
        """Get the current Mneme configuration.

        Returns:
            Current configuration as a dictionary.
        """
        _ensure_initialized()
        return state["config"].model_dump()

    @mcp.tool()
    def update_config(key: str, value: str) -> dict:
        """Update a configuration setting. Use dot-notation for nested keys.

        Args:
            key: Config key in dot-notation (e.g. "search.top_k").
            value: New value as string (will be parsed to appropriate type).

        Returns:
            Updated key with old and new values. Note: some changes require restart.
        """
        _ensure_initialized()
        cfg = state["config"]
        parts = key.split(".")

        if len(parts) != 2:
            return {"error": f"Key must be in format 'section.setting', got '{key}'"}

        section_name, setting_name = parts
        section = getattr(cfg, section_name, None)
        if section is None:
            return {"error": f"Unknown config section: {section_name}"}

        if not hasattr(section, setting_name):
            return {"error": f"Unknown setting: {key}"}

        old_value = getattr(section, setting_name)

        # Parse value to match existing type
        target_type = type(old_value)
        try:
            if target_type == bool:
                parsed = value.lower() in ("true", "1", "yes")
            elif target_type == int:
                parsed = int(value)
            elif target_type == float:
                parsed = float(value)
            elif target_type == list:
                import json
                parsed = json.loads(value)
            else:
                parsed = value
        except (ValueError, TypeError) as e:
            return {"error": f"Cannot parse '{value}' as {target_type.__name__}: {e}"}

        setattr(section, setting_name, parsed)
        save_config(cfg)

        needs_restart = key.startswith("embedding.")
        result = {
            "updated_key": key,
            "old_value": str(old_value),
            "new_value": str(parsed),
        }
        if needs_restart:
            result["warning"] = "Embedding settings changed — run 'reindex --full' to apply."

        return result

    return mcp
