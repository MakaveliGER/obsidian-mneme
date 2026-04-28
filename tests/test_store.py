"""Tests for mneme.store."""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from mneme.store import CURRENT_SCHEMA_VERSION, ChunkData, MnemeSchemaError, Store


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


class TestFTS5Sanitizer:
    def test_hyphenated_query(self, store: Store):
        """Hyphens must not crash FTS5 (interpreted as column operator)."""
        note_id = store.upsert_note("ki.md", "KI", "h", {}, [], [])
        store.upsert_chunks(note_id, [
            ChunkData("KI-Consulting und Beratung", "## KI", 0, _random_vec()),
        ])
        # This would crash without sanitization: "no such column: Consulting"
        results = store.bm25_search("KI-Consulting", top_k=5)
        assert len(results) >= 1
        assert results[0].note_path == "ki.md"

    def test_special_characters(self, store: Store):
        """Queries with special FTS5 operators must not crash."""
        note_id = store.upsert_note("test.md", "Test", "h", {}, [], [])
        store.upsert_chunks(note_id, [
            ChunkData("C++ programming and code*", "## Code", 0, _random_vec()),
        ])
        # * and + are FTS5 operators
        results = store.bm25_search("C++ code*", top_k=5)
        assert isinstance(results, list)  # no crash

    def test_sanitize_preserves_words(self):
        from mneme.store import Store
        # Tokens are OR-joined so FTS5 returns recall-style hits even when
        # a stopword / rare token in the user query is absent.
        assert Store._sanitize_fts5_query("KI-Consulting") == '"KI" OR "Consulting"'
        assert Store._sanitize_fts5_query("hello world") == '"hello" OR "world"'
        assert Store._sanitize_fts5_query("simple") == '"simple"'


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


class TestSchemaVersion:
    def test_fresh_db_sets_current_version(self, tmp_path: Path):
        s = Store(tmp_path / "fresh.db", embedding_dim=DIM)
        row = s._conn.execute(
            "SELECT value FROM _meta WHERE key = 'schema_version'"
        ).fetchone()
        s.close()
        assert row is not None
        assert int(row[0]) == CURRENT_SCHEMA_VERSION

    def test_matching_version_reopens_cleanly(self, tmp_path: Path):
        db = tmp_path / "reopen.db"
        s1 = Store(db, embedding_dim=DIM)
        s1.close()
        # Reopen — must not raise
        s2 = Store(db, embedding_dim=DIM)
        s2.close()

    def test_legacy_db_raises(self, tmp_path: Path):
        db = tmp_path / "legacy.db"
        # Build a store, insert a note, then wipe the schema_version row to
        # simulate a pre-v2 DB that pre-dated the `_meta` table.
        s = Store(db, embedding_dim=DIM, skip_version_check=True)
        s.upsert_note("a.md", "A", "h", {}, [], [])
        s._conn.execute("DELETE FROM _meta WHERE key = 'schema_version'")
        s._conn.commit()
        s.close()

        with pytest.raises(MnemeSchemaError, match="Legacy DB"):
            Store(db, embedding_dim=DIM)

    def test_older_version_raises_with_migration_hint(self, tmp_path: Path):
        db = tmp_path / "old.db"
        s = Store(db, embedding_dim=DIM)
        # v1 is older than the oldest auto-migration path (v2 -> v3) and must
        # still raise. Newer auto-migrations are covered by their own test.
        s.set_schema_version(1)
        s.upsert_note("a.md", "A", "h", {}, [], [])
        s.close()

        with pytest.raises(MnemeSchemaError, match="reindex --full"):
            Store(db, embedding_dim=DIM)

    def test_v2_to_v3_auto_migration(self, tmp_path: Path):
        """A v2 DB must gain the `modified_at` column and have it backfilled
        from `updated_at` automatically — no manual reindex required."""
        db = tmp_path / "v2.db"
        s = Store(db, embedding_dim=DIM)
        s.upsert_note("a.md", "A", "h", {}, [], [])
        # Simulate a v2 DB: drop modified_at, pin version to 2.
        s._conn.execute("ALTER TABLE notes DROP COLUMN modified_at")
        s._conn.commit()
        s.set_schema_version(2)
        s.close()

        # Reopen — migration should run silently.
        s2 = Store(db, embedding_dim=DIM)
        row = s2._conn.execute(
            "SELECT updated_at, modified_at FROM notes WHERE path = 'a.md'"
        ).fetchone()
        assert row[1] is not None, "modified_at must be backfilled"
        assert row[0] == row[1], "backfill must mirror updated_at verbatim"

        version = s2._conn.execute(
            "SELECT value FROM _meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert int(version) == CURRENT_SCHEMA_VERSION
        s2.close()

    def test_newer_version_raises(self, tmp_path: Path):
        db = tmp_path / "newer.db"
        s = Store(db, embedding_dim=DIM)
        s.set_schema_version(CURRENT_SCHEMA_VERSION + 99)
        s.close()

        with pytest.raises(MnemeSchemaError, match="newer than this Mneme"):
            Store(db, embedding_dim=DIM)

    def test_skip_version_check_bypasses(self, tmp_path: Path):
        db = tmp_path / "bypass.db"
        s = Store(db, embedding_dim=DIM)
        s.set_schema_version(CURRENT_SCHEMA_VERSION - 1)
        s.upsert_note("a.md", "A", "h", {}, [], [])
        s.close()

        # With the bypass flag, reopening the same old DB must not raise.
        s2 = Store(db, embedding_dim=DIM, skip_version_check=True)
        s2.close()


class TestOpenMetadataOnly:
    def test_fresh_db_skips_vec_table(self, tmp_path: Path):
        db = tmp_path / "meta.db"
        s = Store.open_metadata_only(db)
        tables = s._conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','virtual_table')"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "notes" in table_names
        assert "chunks_fts" in table_names
        assert "chunks_vec" not in table_names, (
            "chunks_vec must not be created by open_metadata_only — "
            "would lock a fresh DB to the wrong vector dim."
        )
        s.close()

    def test_real_store_after_metadata_open_picks_right_dim(self, tmp_path: Path):
        """Regression: open_metadata_only then Store(embedding_dim=1024) — the
        vec table must end up with dim=1024, not a previously baked dummy dim."""
        db = tmp_path / "seq.db"

        s_meta = Store.open_metadata_only(db)
        s_meta.close()

        s_real = Store(db, embedding_dim=1024)
        # Verify chunks_vec now exists and accepts 1024-dim vectors.
        tables = s_real._conn.execute(
            "SELECT name FROM sqlite_master WHERE name='chunks_vec'"
        ).fetchall()
        assert tables, "chunks_vec must be created by the real Store opener"

        # Insert a 1024-dim vec — would fail with 'dimension mismatch' if the
        # table had been pre-baked to dim=1.
        note_id = s_real.upsert_note("x.md", "X", "h", {}, [], [])
        s_real.upsert_chunks(
            note_id,
            [
                ChunkData(
                    content="c",
                    heading_path="## x",
                    chunk_index=0,
                    embedding=_random_vec(1024),
                )
            ],
        )
        s_real.close()

    def test_metadata_only_can_read_stats_and_bm25(self, tmp_path: Path):
        db = tmp_path / "bm25.db"
        # Seed data with a real Store (dim=16)
        s = Store(db, embedding_dim=DIM)
        _insert_note_with_chunks(s, "a.md", "Alpha note")
        s.close()

        # Metadata-only: stats + BM25 must still work.
        s_meta = Store.open_metadata_only(db)
        stats = s_meta.get_stats(embedding_model="bge-m3")
        assert stats.total_notes == 1
        hits = s_meta.bm25_search("Alpha", top_k=3)
        assert any("a.md" in r.note_path for r in hits)
        s_meta.close()
