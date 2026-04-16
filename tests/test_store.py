"""Tests for mneme.store."""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from mneme.store import ChunkData, Store


DIM = 16  # small dimension for fast tests


def _random_vec(dim: int = DIM) -> list[float]:
    """Generate a random normalized vector."""
    vec = [random.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


@pytest.fixture
def store(tmp_path: Path) -> Store:
    db = tmp_path / "test.db"
    s = Store(db, embedding_dim=DIM)
    yield s
    s.close()


def _insert_note_with_chunks(store: Store, path: str, title: str, n_chunks: int = 2) -> int:
    note_id = store.upsert_note(
        path=path,
        title=title,
        content_hash="hash123",
        frontmatter={"key": "value"},
        tags=["alpha", "beta"],
        wikilinks=["Link1"],
    )
    chunks = [
        ChunkData(
            content=f"Content of chunk {i} for {title}",
            heading_path=f"## Section {i}",
            chunk_index=i,
            embedding=_random_vec(),
        )
        for i in range(n_chunks)
    ]
    store.upsert_chunks(note_id, chunks)
    return note_id


class TestSchema:
    def test_tables_exist(self, store: Store):
        tables = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "notes" in table_names
        assert "chunks" in table_names
        assert "chunks_fts" in table_names

    def test_vec_table_exists(self, store: Store):
        # vec0 tables appear as virtual tables
        rows = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE name='chunks_vec'"
        ).fetchall()
        assert len(rows) == 1


class TestNotes:
    def test_upsert_and_get(self, store: Store):
        note_id = store.upsert_note(
            path="test/note.md",
            title="My Note",
            content_hash="abc123",
            frontmatter={"status": "active"},
            tags=["tag1", "tag2"],
            wikilinks=["Link1"],
        )
        assert note_id > 0
        note = store.get_note_by_path("test/note.md")
        assert note is not None
        assert note["title"] == "My Note"
        assert note["content_hash"] == "abc123"
        assert note["tags"] == ["tag1", "tag2"]
        assert note["frontmatter"]["status"] == "active"

    def test_upsert_same_path_updates(self, store: Store):
        store.upsert_note("note.md", "V1", "hash1", {}, [], [])
        store.upsert_note("note.md", "V2", "hash2", {}, [], [])
        note = store.get_note_by_path("note.md")
        assert note["title"] == "V2"
        assert note["content_hash"] == "hash2"
        # Only one note in DB
        count = store._conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        assert count == 1

    def test_get_nonexistent(self, store: Store):
        assert store.get_note_by_path("nope.md") is None

    def test_delete_note(self, store: Store):
        _insert_note_with_chunks(store, "del.md", "Delete Me", n_chunks=3)
        assert store.delete_note("del.md") is True
        assert store.get_note_by_path("del.md") is None
        # Chunks should be gone too
        count = store._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        assert count == 0

    def test_delete_nonexistent(self, store: Store):
        assert store.delete_note("ghost.md") is False


class TestChunks:
    def test_upsert_chunks_creates_entries(self, store: Store):
        _insert_note_with_chunks(store, "note.md", "Note", n_chunks=3)
        count = store._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        assert count == 3

    def test_upsert_chunks_replaces_old(self, store: Store):
        note_id = _insert_note_with_chunks(store, "note.md", "Note", n_chunks=3)
        # Re-insert with 2 chunks
        new_chunks = [
            ChunkData(f"New {i}", f"## New {i}", i, _random_vec())
            for i in range(2)
        ]
        store.upsert_chunks(note_id, new_chunks)
        count = store._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        assert count == 2


class TestVectorSearch:
    def test_finds_similar(self, store: Store):
        # Insert a note with known embedding
        target_vec = _random_vec()
        note_id = store.upsert_note("target.md", "Target", "h", {}, ["t"], [])
        store.upsert_chunks(note_id, [
            ChunkData("Target content", "## Target", 0, target_vec),
        ])

        # Insert a different note
        _insert_note_with_chunks(store, "other.md", "Other", n_chunks=1)

        results = store.vector_search(target_vec, top_k=5)
        assert len(results) >= 1
        # First result should be the target (exact match)
        assert results[0].note_path == "target.md"
        assert results[0].score > 0.9  # cosine similarity ≈ 1.0

    def test_returns_metadata(self, store: Store):
        _insert_note_with_chunks(store, "meta.md", "Meta Note", n_chunks=1)
        vec = _random_vec()
        results = store.vector_search(vec, top_k=5)
        assert len(results) >= 1
        r = results[0]
        assert r.note_title == "Meta Note"
        assert r.heading_path is not None
        assert isinstance(r.tags, list)


class TestBM25Search:
    def test_finds_by_keyword(self, store: Store):
        note_id = store.upsert_note("kw.md", "Keyword Note", "h", {}, ["test"], [])
        store.upsert_chunks(note_id, [
            ChunkData("The quick brown fox jumps over the lazy dog", "## Animals", 0, _random_vec()),
        ])
        results = store.bm25_search("quick fox", top_k=5)
        assert len(results) >= 1
        assert results[0].note_path == "kw.md"

    def test_no_results(self, store: Store):
        _insert_note_with_chunks(store, "note.md", "Note", n_chunks=1)
        results = store.bm25_search("xyznonexistent", top_k=5)
        assert len(results) == 0

    def test_tag_filter(self, store: Store):
        note_id = store.upsert_note("tagged.md", "Tagged", "h", {}, ["python"], [])
        store.upsert_chunks(note_id, [
            ChunkData("Python programming language", "## Code", 0, _random_vec()),
        ])
        note_id2 = store.upsert_note("untagged.md", "Untagged", "h", {}, ["java"], [])
        store.upsert_chunks(note_id2, [
            ChunkData("Python also used here", "## Code", 0, _random_vec()),
        ])

        results = store.bm25_search("Python", top_k=5, tags=["python"])
        paths = [r.note_path for r in results]
        assert "tagged.md" in paths
        assert "untagged.md" not in paths


class TestStats:
    def test_counts(self, store: Store):
        _insert_note_with_chunks(store, "a.md", "A", n_chunks=2)
        _insert_note_with_chunks(store, "b.md", "B", n_chunks=3)
        stats = store.get_stats(embedding_model="test-model")
        assert stats.total_notes == 2
        assert stats.total_chunks == 5
        assert stats.embedding_model == "test-model"
        assert stats.last_indexed is not None
        assert stats.db_size_mb >= 0

    def test_empty_db(self, store: Store):
        stats = store.get_stats()
        assert stats.total_notes == 0
        assert stats.total_chunks == 0


class TestGetAllNotePaths:
    def test_returns_paths(self, store: Store):
        _insert_note_with_chunks(store, "a.md", "A")
        _insert_note_with_chunks(store, "b.md", "B")
        paths = store.get_all_note_paths()
        assert sorted(paths) == ["a.md", "b.md"]


class TestGetEmbeddings:
    def test_roundtrip(self, store: Store):
        vec = _random_vec()
        note_id = store.upsert_note("emb.md", "Emb", "h", {}, [], [])
        store.upsert_chunks(note_id, [
            ChunkData("Content", "##", 0, vec),
        ])
        retrieved = store.get_all_chunk_embeddings_for_note("emb.md")
        assert len(retrieved) == 1
        for orig, ret in zip(vec, retrieved[0]):
            assert abs(orig - ret) < 1e-5
