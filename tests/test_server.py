"""Tests for mneme.server — MCP server tool definitions."""

from __future__ import annotations

import asyncio
import math
import random
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mneme.config import MnemeConfig, VaultConfig, EmbeddingConfig, DatabaseConfig, ChunkingConfig
from mneme.server import create_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIM = 16


class MockEmbeddingProvider:
    """Deterministic-ish mock that returns normalized random vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for _ in texts:
            v = [random.gauss(0, 1) for _ in range(DIM)]
            norm = math.sqrt(sum(x * x for x in v))
            vecs.append([x / norm for x in v])
        return vecs

    def dimension(self) -> int:
        return DIM

    def warmup(self) -> None:
        pass


def _call(tool_name: str, server, **kwargs):
    """Synchronously invoke a FastMCP tool by name."""
    tool = server._tool_manager._tools[tool_name]
    return asyncio.run(tool.run(kwargs))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def server_with_vault(tmp_path: Path):
    """
    Create a test vault with 3 notes and an indexed server.

    note1.md  — has frontmatter tags [python, test], no links
    note2.md  — links to note1 via [[note1]]
    subfolder/note3.md  — orphan (no links in or out, inside a subfolder)

    The fixture yields (server, config) and stops the file watcher on teardown.
    """
    vault = tmp_path / "vault"
    vault.mkdir()

    (vault / "note1.md").write_text(
        "---\ntags: [python, test]\n---\n## Code\n\nPython programming tutorial about functions and classes.",
        encoding="utf-8",
    )
    (vault / "note2.md").write_text(
        "## Links\n\n[[note1]] is referenced here. Machine learning basics.",
        encoding="utf-8",
    )
    sub = vault / "subfolder"
    sub.mkdir()
    (sub / "note3.md").write_text(
        "## Deep\n\nOrphan note without links in subfolder.",
        encoding="utf-8",
    )

    db_path = tmp_path / "test.db"
    config = MnemeConfig(
        vault=VaultConfig(path=str(vault)),
        database=DatabaseConfig(path=str(db_path)),
        chunking=ChunkingConfig(max_tokens=200, overlap_tokens=20),
    )

    with patch("mneme.server.get_provider") as mock_get:
        mock_get.return_value = MockEmbeddingProvider()
        server = create_server(config, eager_init=False)

    # Index all notes so tests have data to work with
    _call("reindex", server, full=True)

    yield server, config

    # Teardown: stop file watcher so watchdog thread releases DB/file handles
    from mneme.watcher import VaultWatcher  # local import to avoid issues

    # The watcher is stored in the closure state dict but not directly exposed.
    # Access it by inspecting the tool manager (the indexer has a back-ref to
    # the store, and VaultWatcher is held by server _initialize closure state).
    # Simplest approach: reach through the tool closures to the state dict
    # via the 'reindex' tool's __closure__.
    reindex_tool = server._tool_manager._tools["reindex"]
    fn = reindex_tool.fn
    state = None
    if hasattr(fn, "__closure__") and fn.__closure__:
        for cell in fn.__closure__:
            try:
                val = cell.cell_contents
                if isinstance(val, dict) and "watcher" in val:
                    state = val
                    break
            except ValueError:
                pass

    if state and "watcher" in state:
        state["watcher"].stop()


# ---------------------------------------------------------------------------
# Existing test (must not break)
# ---------------------------------------------------------------------------

def test_server_has_eight_tools(tmp_path: Path):
    """The MCP server must expose exactly 8 tools."""
    db_path = tmp_path / "test.db"
    config = MnemeConfig(
        vault=VaultConfig(path=str(tmp_path)),
        database=DatabaseConfig(path=str(db_path)),
    )

    with patch("mneme.server.get_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.dimension.return_value = 16
        mock_get_provider.return_value = mock_provider
        server = create_server(config, eager_init=False)

    tool_names = list(server._tool_manager._tools.keys())
    assert len(tool_names) == 8
    expected = {
        "search_notes", "get_similar", "get_note_context", "vault_stats",
        "reindex", "get_config", "update_config", "vault_health",
    }
    assert set(tool_names) == expected


# ---------------------------------------------------------------------------
# search_notes
# ---------------------------------------------------------------------------

def test_search_notes_returns_results(server_with_vault):
    server, _ = server_with_vault
    result = _call("search_notes", server, query="Python programming", top_k=5)

    assert "results" in result
    assert result["total_results"] > 0
    paths = [r["path"] for r in result["results"]]
    assert any("note1" in p for p in paths), f"Expected note1 in results, got {paths}"


def test_search_notes_empty_query(server_with_vault):
    server, _ = server_with_vault
    # A very short / non-meaningful query should not crash; may return 0 or more results
    result = _call("search_notes", server, query="a", top_k=5)
    assert "results" in result
    assert isinstance(result["total_results"], int)


def test_search_notes_tag_filter(server_with_vault):
    server, _ = server_with_vault
    result = _call("search_notes", server, query="programming", tags=["python"], top_k=10)

    assert "results" in result
    # All returned notes must carry the 'python' tag
    for r in result["results"]:
        assert "python" in r["tags"], f"Note {r['path']} lacks 'python' tag: {r['tags']}"
    # note1 is the only note with tag python — must appear
    paths = [r["path"] for r in result["results"]]
    assert any("note1" in p for p in paths)


def test_search_notes_folder_filter(server_with_vault):
    server, _ = server_with_vault
    result = _call("search_notes", server, query="note", folders=["subfolder"], top_k=10)

    assert "results" in result
    # Every result must live inside subfolder
    for r in result["results"]:
        assert "subfolder" in r["path"], f"Path {r['path']!r} not inside subfolder"


# ---------------------------------------------------------------------------
# get_similar
# ---------------------------------------------------------------------------

def test_get_similar_valid_path(server_with_vault):
    server, _ = server_with_vault
    result = _call("get_similar", server, path="note1.md", top_k=3)

    assert "results" in result
    assert result["source_path"] == "note1.md"
    # None of the similar results should be note1 itself
    for r in result["results"]:
        assert "note1" not in r["path"] or r["path"] != "note1.md"


def test_get_similar_nonexistent_path(server_with_vault):
    server, _ = server_with_vault
    result = _call("get_similar", server, path="does_not_exist.md", top_k=3)

    assert result["total_results"] == 0
    assert result["results"] == []


# ---------------------------------------------------------------------------
# get_note_context
# ---------------------------------------------------------------------------

def test_get_note_context_returns_bundle(server_with_vault):
    server, _ = server_with_vault
    result = _call("get_note_context", server, path="note1.md")

    assert "note" in result
    assert "graph_neighbors" in result
    assert "similar_notes" in result
    assert result["note"]["path"] == "note1.md"
    # note2 links to note1 → note1 should have at least one neighbor
    assert result["total_neighbors"] >= 1


def test_get_note_context_nonexistent(server_with_vault):
    server, _ = server_with_vault
    result = _call("get_note_context", server, path="ghost.md")

    assert "error" in result
    assert "ghost.md" in result["error"]


# ---------------------------------------------------------------------------
# vault_stats
# ---------------------------------------------------------------------------

def test_vault_stats_returns_counts(server_with_vault):
    server, _ = server_with_vault
    result = _call("vault_stats", server)

    assert result["total_notes"] == 3
    assert result["total_chunks"] >= 3
    assert result["total_chunks"] >= result["total_notes"]
    assert "last_indexed" in result
    assert result["last_indexed"] is not None


# ---------------------------------------------------------------------------
# vault_health
# ---------------------------------------------------------------------------

def test_vault_health_orphans(server_with_vault):
    server, _ = server_with_vault
    result = _call("vault_health", server, checks=["orphans"])

    assert "orphan_pages" in result
    orphan_paths = [o["path"] for o in result["orphan_pages"]]
    # note3 inside subfolder/ has no links at all → must be an orphan
    assert any("note3" in p for p in orphan_paths), (
        f"Expected note3 to be an orphan, got: {orphan_paths}"
    )


# ---------------------------------------------------------------------------
# reindex
# ---------------------------------------------------------------------------

def test_reindex_incremental(server_with_vault):
    """After a full index, incremental re-index should report 0 newly indexed."""
    server, _ = server_with_vault
    # vault was fully indexed in fixture — incremental run should skip all 3
    result = _call("reindex", server, full=False)

    assert result["indexed"] == 0
    assert result["skipped"] == 3


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------

def test_get_config_returns_dict(server_with_vault):
    server, _ = server_with_vault
    result = _call("get_config", server)

    # Top-level config sections must be present
    for key in ("vault", "embedding", "search"):
        assert key in result, f"Missing key '{key}' in config dict"
    # MCP get_config redacts vault.path/database.path to <set>/<unset>
    # so prompt-injected Claude can't exfiltrate filesystem layout.
    assert result["vault"]["path"] == "<set>"


# ---------------------------------------------------------------------------
# update_config
# ---------------------------------------------------------------------------

def test_update_config_changes_value(server_with_vault):
    server, _ = server_with_vault

    # Patch save_config so we don't write to the real user config dir
    with patch("mneme.server.save_config") as mock_save:
        result = _call("update_config", server, key="search.top_k", value="42")

    assert "error" not in result
    assert result["updated_key"] == "search.top_k"
    assert result["old_value"] == "10"   # default top_k is 10
    assert result["new_value"] == "42"
    mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------

def test_server_has_resources(tmp_path: Path):
    """The MCP server must expose at least 3 resources."""
    db_path = tmp_path / "test.db"
    config = MnemeConfig(
        vault=VaultConfig(path=str(tmp_path)),
        database=DatabaseConfig(path=str(db_path)),
    )

    with patch("mneme.server.get_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.dimension.return_value = 16
        mock_get_provider.return_value = mock_provider
        server = create_server(config, eager_init=False)

    resources = server._resource_manager._resources
    assert len(resources) >= 3
    uris = set(resources.keys())
    assert "mneme://vault/stats" in uris
    assert "mneme://vault/tags" in uris
    assert "mneme://vault/graph-summary" in uris


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------

def test_server_has_prompts(tmp_path: Path):
    """The MCP server must expose at least 3 prompts."""
    db_path = tmp_path / "test.db"
    config = MnemeConfig(
        vault=VaultConfig(path=str(tmp_path)),
        database=DatabaseConfig(path=str(db_path)),
    )

    with patch("mneme.server.get_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.dimension.return_value = 16
        mock_get_provider.return_value = mock_provider
        server = create_server(config, eager_init=False)

    prompts = server._prompt_manager._prompts
    assert len(prompts) >= 3
    names = set(prompts.keys())
    assert "research_topic" in names
    assert "vault_review" in names
    assert "find_connections" in names
