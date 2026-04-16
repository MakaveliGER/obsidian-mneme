"""Tests for mneme.indexer."""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from mneme.config import MnemeConfig, VaultConfig, ChunkingConfig
from mneme.embeddings.base import EmbeddingProvider
from mneme.indexer import Indexer, IndexResult
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
def test_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()

    # Note 1 — with frontmatter
    (vault / "note1.md").write_text(
        "---\ntags: [test]\n---\n## Section 1\n\nContent of note one with enough words for chunking.",
        encoding="utf-8",
    )
    # Note 2 — with wikilinks
    (vault / "note2.md").write_text(
        "## Links\n\nSee [[note1]] for details. More content here to ensure chunk.",
        encoding="utf-8",
    )
    # Subfolder note
    sub = vault / "subfolder"
    sub.mkdir()
    (sub / "note3.md").write_text(
        "## Deep\n\nThis is a deep note with sufficient content words.",
        encoding="utf-8",
    )
    # Excluded — .obsidian folder
    obs = vault / ".obsidian"
    obs.mkdir()
    (obs / "config.md").write_text("Should be excluded", encoding="utf-8")

    return vault


def _make_indexer(vault: Path, tmp_path: Path):
    """Build an Indexer wired to an in-memory (tmp) SQLite store."""
    config = MnemeConfig(
        vault=VaultConfig(
            path=str(vault),
            glob_patterns=["**/*.md"],
            exclude_patterns=[".obsidian/**", ".trash/**"],
        ),
        chunking=ChunkingConfig(max_tokens=200, overlap_tokens=20),
    )
    db_path = tmp_path / "test.db"
    store = Store(db_path, embedding_dim=DIM)
    provider = MockEmbeddingProvider()
    return Indexer(store=store, embedding_provider=provider, config=config), store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_index_vault_full(test_vault: Path, tmp_path: Path) -> None:
    """Full index: all 3 real notes indexed, .obsidian file ignored."""
    indexer, store = _make_indexer(test_vault, tmp_path)
    result = indexer.index_vault(full=True)

    assert result.indexed == 3, f"Expected 3 indexed, got {result.indexed}"
    assert result.skipped == 0
    assert result.deleted == 0
    assert result.duration_seconds >= 0

    paths = store.get_all_note_paths()
    assert len(paths) == 3
    assert not any(".obsidian" in p for p in paths)


def test_index_vault_incremental(test_vault: Path, tmp_path: Path) -> None:
    """Second run without changes → all skipped, nothing indexed."""
    indexer, store = _make_indexer(test_vault, tmp_path)

    first = indexer.index_vault(full=False)
    assert first.indexed == 3

    second = indexer.index_vault(full=False)
    assert second.indexed == 0
    assert second.skipped == 3
    assert second.deleted == 0


def test_index_vault_changed_file(test_vault: Path, tmp_path: Path) -> None:
    """Changing one file causes only that file to be re-indexed."""
    indexer, store = _make_indexer(test_vault, tmp_path)

    indexer.index_vault(full=False)

    # Modify note1
    (test_vault / "note1.md").write_text(
        "---\ntags: [test, updated]\n---\n## Section 1\n\nUpdated content for note one.",
        encoding="utf-8",
    )

    second = indexer.index_vault(full=False)
    assert second.indexed == 1
    assert second.skipped == 2
    assert second.deleted == 0


def test_index_vault_deleted_file(test_vault: Path, tmp_path: Path) -> None:
    """Deleting a vault file removes it from the DB (deleted=1)."""
    indexer, store = _make_indexer(test_vault, tmp_path)
    indexer.index_vault(full=True)

    # Remove note2 from disk
    (test_vault / "note2.md").unlink()

    second = indexer.index_vault(full=False)
    assert second.deleted == 1

    paths = store.get_all_note_paths()
    assert len(paths) == 2
    assert not any("note2" in p for p in paths)


def test_exclude_patterns(test_vault: Path, tmp_path: Path) -> None:
    """.obsidian/ and .trash/ are excluded even if they contain .md files."""
    trash = test_vault / ".trash"
    trash.mkdir()
    (trash / "deleted.md").write_text("Deleted note content here.", encoding="utf-8")

    indexer, store = _make_indexer(test_vault, tmp_path)
    result = indexer.index_vault(full=True)

    assert result.indexed == 3

    paths = store.get_all_note_paths()
    assert not any(".obsidian" in p for p in paths)
    assert not any(".trash" in p for p in paths)


def test_index_file_single(test_vault: Path, tmp_path: Path) -> None:
    """index_file() indexes a single file and returns True."""
    indexer, store = _make_indexer(test_vault, tmp_path)

    file_path = test_vault / "note1.md"
    result = indexer.index_file(file_path)
    assert result is True

    paths = store.get_all_note_paths()
    assert len(paths) == 1
    assert any("note1" in p for p in paths)


def test_index_file_single_skipped_when_unchanged(test_vault: Path, tmp_path: Path) -> None:
    """index_file() returns False when the file hash hasn't changed."""
    indexer, _ = _make_indexer(test_vault, tmp_path)

    file_path = test_vault / "note1.md"
    first = indexer.index_file(file_path)
    assert first is True

    second = indexer.index_file(file_path)
    assert second is False


def test_remove_file(test_vault: Path, tmp_path: Path) -> None:
    """remove_file() deletes an indexed note and returns True."""
    indexer, store = _make_indexer(test_vault, tmp_path)
    indexer.index_vault(full=True)

    paths = store.get_all_note_paths()
    note1_path = next(p for p in paths if "note1" in p)

    removed = indexer.remove_file(note1_path)
    assert removed is True

    remaining = store.get_all_note_paths()
    assert len(remaining) == 2
    assert note1_path not in remaining


def test_remove_file_nonexistent(test_vault: Path, tmp_path: Path) -> None:
    """remove_file() returns False for a path that isn't in the index."""
    indexer, _ = _make_indexer(test_vault, tmp_path)
    result = indexer.remove_file("nonexistent/note.md")
    assert result is False
