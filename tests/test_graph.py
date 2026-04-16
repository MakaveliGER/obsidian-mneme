"""Tests for the Wikilink graph: alias_map, link resolution, graph traversal."""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from mneme.config import ChunkingConfig, MnemeConfig, VaultConfig
from mneme.embeddings.base import EmbeddingProvider
from mneme.indexer import Indexer
from mneme.store import Store


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

DIM = 16


class MockEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for _ in texts:
            v = [random.gauss(0, 1) for _ in range(DIM)]
            n = math.sqrt(sum(x * x for x in v))
            vecs.append([x / n for x in v])
        return vecs

    def dimension(self) -> int:
        return DIM


@pytest.fixture
def graph_vault(tmp_path: Path) -> Path:
    """Four notes that cross-link each other."""
    vault = tmp_path / "vault"
    vault.mkdir()

    (vault / "note_a.md").write_text("[[note_b]] und [[note_c]]", encoding="utf-8")
    (vault / "note_b.md").write_text("[[note_a]]", encoding="utf-8")
    (vault / "note_c.md").write_text("[[note_a]] und [[subfolder/note_d]]", encoding="utf-8")

    sub = vault / "subfolder"
    sub.mkdir()
    (sub / "note_d.md").write_text("[[note_b]]", encoding="utf-8")

    return vault


@pytest.fixture
def store(tmp_path: Path) -> Store:
    db = tmp_path / "graph_test.db"
    s = Store(db, embedding_dim=DIM)
    yield s
    s.close()


@pytest.fixture
def populated_store(graph_vault: Path, tmp_path: Path) -> tuple[Store, dict[str, int]]:
    """Store with all 4 notes inserted (no link resolution yet)."""
    db = tmp_path / "graph_test.db"
    s = Store(db, embedding_dim=DIM)

    note_ids: dict[str, int] = {}
    notes = [
        ("note_a.md", "note_a", ["note_b", "note_c"]),
        ("note_b.md", "note_b", ["note_a"]),
        ("note_c.md", "note_c", ["note_a", "subfolder/note_d"]),
        ("subfolder/note_d.md", "note_d", ["note_b"]),
    ]
    for path, title, wikilinks in notes:
        nid = s.upsert_note(
            path=path,
            title=title,
            content_hash=f"hash_{title}",
            frontmatter={},
            tags=[],
            wikilinks=wikilinks,
        )
        note_ids[title] = nid

    yield s, note_ids
    s.close()


def _make_indexer(vault: Path, tmp_path: Path) -> tuple[Indexer, Store]:
    config = MnemeConfig(
        vault=VaultConfig(
            path=str(vault),
            glob_patterns=["**/*.md"],
            exclude_patterns=[],
        ),
        chunking=ChunkingConfig(max_tokens=200, overlap_tokens=20),
    )
    db_path = tmp_path / "indexer_graph.db"
    s = Store(db_path, embedding_dim=DIM)
    provider = MockEmbeddingProvider()
    return Indexer(store=s, embedding_provider=provider, config=config), s


# ---------------------------------------------------------------------------
# alias_map tests
# ---------------------------------------------------------------------------

def test_alias_map_basenames(populated_store: tuple[Store, dict[str, int]]) -> None:
    """Basenames without extension are resolvable."""
    store, note_ids = populated_store
    alias_map = store.build_alias_map()

    assert alias_map["note_a"] == note_ids["note_a"]
    assert alias_map["note_b"] == note_ids["note_b"]
    assert alias_map["note_c"] == note_ids["note_c"]
    assert alias_map["note_d"] == note_ids["note_d"]


def test_alias_map_full_paths(populated_store: tuple[Store, dict[str, int]]) -> None:
    """Full paths (without .md) are resolvable."""
    store, note_ids = populated_store
    alias_map = store.build_alias_map()

    assert alias_map["note_a"] == note_ids["note_a"]
    assert alias_map["subfolder/note_d"] == note_ids["note_d"]


def test_alias_map_conflict(store: Store) -> None:
    """Two notes sharing the same basename: basename key absent, full paths present."""
    id1 = store.upsert_note("folder1/conflict.md", "C1", "h1", {}, [], [])
    id2 = store.upsert_note("folder2/conflict.md", "C2", "h2", {}, [], [])

    alias_map = store.build_alias_map()

    # Basename is ambiguous — must NOT appear
    assert "conflict" not in alias_map

    # Full paths must be present
    assert alias_map["folder1/conflict"] == id1
    assert alias_map["folder2/conflict"] == id2


# ---------------------------------------------------------------------------
# resolve_and_store_links tests
# ---------------------------------------------------------------------------

def test_resolve_links(populated_store: tuple[Store, dict[str, int]]) -> None:
    """Links for note_a are written to the links table correctly."""
    store, note_ids = populated_store
    alias_map = store.build_alias_map()

    resolved = store.resolve_and_store_links(
        note_ids["note_a"], ["note_b", "note_c"], alias_map
    )

    assert resolved == 2

    rows = store._conn.execute(
        "SELECT target_id FROM links WHERE source_id = ? ORDER BY target_id",
        (note_ids["note_a"],),
    ).fetchall()
    target_ids = {r[0] for r in rows}
    assert target_ids == {note_ids["note_b"], note_ids["note_c"]}


# ---------------------------------------------------------------------------
# get_linked_notes / get_backlinks
# ---------------------------------------------------------------------------

def _resolve_all(store: Store, note_ids: dict[str, int]) -> None:
    """Helper: resolve links for all test notes."""
    wikilinks_map = {
        "note_a": ["note_b", "note_c"],
        "note_b": ["note_a"],
        "note_c": ["note_a", "subfolder/note_d"],
        "note_d": ["note_b"],
    }
    alias_map = store.build_alias_map()
    for title, nid in note_ids.items():
        store.resolve_and_store_links(nid, wikilinks_map[title], alias_map)


def test_get_linked_notes(populated_store: tuple[Store, dict[str, int]]) -> None:
    """Outgoing links from note_a → note_b and note_c."""
    store, note_ids = populated_store
    _resolve_all(store, note_ids)

    linked = store.get_linked_notes(note_ids["note_a"])
    linked_ids = {n["id"] for n in linked}

    assert note_ids["note_b"] in linked_ids
    assert note_ids["note_c"] in linked_ids
    assert len(linked) == 2


def test_get_backlinks(populated_store: tuple[Store, dict[str, int]]) -> None:
    """Incoming links to note_a → note_b and note_c both link to it."""
    store, note_ids = populated_store
    _resolve_all(store, note_ids)

    backlinks = store.get_backlinks(note_ids["note_a"])
    backlink_ids = {n["id"] for n in backlinks}

    assert note_ids["note_b"] in backlink_ids
    assert note_ids["note_c"] in backlink_ids
    assert len(backlinks) == 2


# ---------------------------------------------------------------------------
# get_graph_neighbors
# ---------------------------------------------------------------------------

def test_get_graph_neighbors_depth1(populated_store: tuple[Store, dict[str, int]]) -> None:
    """Depth-1 neighbors of note_a: note_b and note_c (direct links in both dirs)."""
    store, note_ids = populated_store
    _resolve_all(store, note_ids)

    neighbors = store.get_graph_neighbors(note_ids["note_a"], depth=1)
    neighbor_ids = {n["id"] for n in neighbors}

    # note_a → note_b, note_a → note_c (outgoing)
    # note_b → note_a, note_c → note_a (incoming, source_id already visited)
    assert note_ids["note_b"] in neighbor_ids
    assert note_ids["note_c"] in neighbor_ids
    assert note_ids["note_a"] not in neighbor_ids  # source excluded


def test_get_graph_neighbors_depth2(populated_store: tuple[Store, dict[str, int]]) -> None:
    """Depth-2 from note_b reaches note_d via note_c."""
    store, note_ids = populated_store
    _resolve_all(store, note_ids)

    neighbors = store.get_graph_neighbors(note_ids["note_b"], depth=2)
    neighbor_ids = {n["id"] for n in neighbors}

    # note_b → note_a (depth 1), note_a → note_c (depth 2), note_c → note_d (depth 2)
    assert note_ids["note_a"] in neighbor_ids
    assert note_ids["note_c"] in neighbor_ids
    assert note_ids["note_d"] in neighbor_ids
    assert note_ids["note_b"] not in neighbor_ids  # source excluded


# ---------------------------------------------------------------------------
# Integration: index_vault builds links
# ---------------------------------------------------------------------------

def test_index_vault_builds_links(graph_vault: Path, tmp_path: Path) -> None:
    """index_vault() populates the links table and reports links_resolved > 0."""
    indexer, store = _make_indexer(graph_vault, tmp_path)
    result = indexer.index_vault(full=True)

    assert result.indexed == 4
    assert result.links_resolved > 0

    # Verify at least one link row exists
    count = store._conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    assert count > 0

    store.close()
