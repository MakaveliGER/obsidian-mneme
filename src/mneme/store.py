"""SQLite store with sqlite-vec (vectors) and FTS5 (BM25 keyword search)."""

from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChunkData:
    content: str
    heading_path: str
    chunk_index: int
    embedding: list[float]


@dataclass
class SearchResult:
    chunk_id: int
    note_path: str
    note_title: str
    heading_path: str
    content: str
    score: float
    tags: list[str]


@dataclass
class IndexStats:
    total_notes: int
    total_chunks: int
    last_indexed: str | None
    embedding_model: str
    db_size_mb: float


def _serialize_float_vec(vec: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


class Store:
    def __init__(self, db_path: Path, embedding_dim: int) -> None:
        self.db_path = db_path
        self.embedding_dim = embedding_dim
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._load_extensions()
        self._create_schema()

    def _load_extensions(self) -> None:
        self._conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)

    def _create_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY,
                path        TEXT UNIQUE NOT NULL,
                title       TEXT,
                content_hash TEXT NOT NULL,
                frontmatter TEXT,
                tags        TEXT,
                wikilinks   TEXT,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id          INTEGER PRIMARY KEY,
                note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                content     TEXT NOT NULL,
                heading_path TEXT,
                chunk_index INTEGER NOT NULL,
                UNIQUE(note_id, chunk_index)
            );
        """)

        # FTS5 virtual table — external content mode synced with chunks
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                content,
                content=chunks,
                content_rowid=id,
                tokenize='unicode61'
            )
        """)

        # sqlite-vec virtual table
        cur.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                embedding float[{self.embedding_dim}]
            )
        """)

        # Triggers to keep FTS5 in sync with chunks
        cur.executescript("""
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content)
                VALUES('delete', old.id, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content)
                VALUES('delete', old.id, old.content);
                INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
            END;
        """)
        self._conn.commit()

    def upsert_note(
        self,
        path: str,
        title: str,
        content_hash: str,
        frontmatter: dict,
        tags: list[str],
        wikilinks: list[str],
    ) -> int:
        """Insert or update a note. Returns note_id."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """INSERT INTO notes (path, title, content_hash, frontmatter, tags, wikilinks, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                   title=excluded.title,
                   content_hash=excluded.content_hash,
                   frontmatter=excluded.frontmatter,
                   tags=excluded.tags,
                   wikilinks=excluded.wikilinks,
                   updated_at=excluded.updated_at""",
            (
                path,
                title,
                content_hash,
                json.dumps(frontmatter),
                json.dumps(tags),
                json.dumps(wikilinks),
                now,
            ),
        )
        # Get the note_id (works for both insert and update)
        row = self._conn.execute(
            "SELECT id FROM notes WHERE path = ?", (path,)
        ).fetchone()
        return row[0]

    def upsert_chunks(self, note_id: int, chunks: list[ChunkData]) -> None:
        """Delete old chunks for note_id, insert new ones with embeddings."""
        cur = self._conn.cursor()

        # Get existing chunk IDs for vec cleanup
        old_ids = [
            r[0]
            for r in cur.execute(
                "SELECT id FROM chunks WHERE note_id = ?", (note_id,)
            ).fetchall()
        ]

        # Delete from vec table first (no CASCADE from chunks)
        for old_id in old_ids:
            cur.execute("DELETE FROM chunks_vec WHERE chunk_id = ?", (old_id,))

        # Delete old chunks (triggers handle FTS5 cleanup)
        cur.execute("DELETE FROM chunks WHERE note_id = ?", (note_id,))

        # Insert new chunks
        for chunk in chunks:
            cur.execute(
                """INSERT INTO chunks (note_id, content, heading_path, chunk_index)
                   VALUES (?, ?, ?, ?)""",
                (note_id, chunk.content, chunk.heading_path, chunk.chunk_index),
            )
            chunk_id = cur.lastrowid

            # Insert embedding into vec table
            cur.execute(
                "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, _serialize_float_vec(chunk.embedding)),
            )

        self._conn.commit()

    def delete_note(self, path: str) -> bool:
        """Delete a note and all its chunks. Returns True if note existed."""
        cur = self._conn.cursor()
        row = cur.execute("SELECT id FROM notes WHERE path = ?", (path,)).fetchone()
        if not row:
            return False

        note_id = row[0]

        # Clean up vec table (no CASCADE)
        chunk_ids = [
            r[0]
            for r in cur.execute(
                "SELECT id FROM chunks WHERE note_id = ?", (note_id,)
            ).fetchall()
        ]
        for cid in chunk_ids:
            cur.execute("DELETE FROM chunks_vec WHERE chunk_id = ?", (cid,))

        # Delete note (CASCADE deletes chunks, triggers clean FTS5)
        cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._conn.commit()
        return True

    def get_note_by_path(self, path: str) -> dict | None:
        """Get note metadata by path."""
        row = self._conn.execute(
            "SELECT id, path, title, content_hash, frontmatter, tags, wikilinks, updated_at "
            "FROM notes WHERE path = ?",
            (path,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "path": row[1],
            "title": row[2],
            "content_hash": row[3],
            "frontmatter": json.loads(row[4]) if row[4] else {},
            "tags": json.loads(row[5]) if row[5] else [],
            "wikilinks": json.loads(row[6]) if row[6] else [],
            "updated_at": row[7],
        }

    def vector_search(self, query_embedding: list[float], top_k: int = 10) -> list[SearchResult]:
        """KNN search via sqlite-vec. No WHERE filtering (sqlite-vec constraint)."""
        rows = self._conn.execute(
            """SELECT cv.chunk_id, cv.distance, c.content, c.heading_path,
                      n.path, n.title, n.tags
               FROM chunks_vec cv
               JOIN chunks c ON c.id = cv.chunk_id
               JOIN notes n ON n.id = c.note_id
               WHERE embedding MATCH ?
               AND k = ?
               ORDER BY distance""",
            (_serialize_float_vec(query_embedding), top_k),
        ).fetchall()

        results = []
        for row in rows:
            results.append(SearchResult(
                chunk_id=row[0],
                note_path=row[4],
                note_title=row[5],
                heading_path=row[3],
                content=row[2],
                score=1.0 - row[1],  # cosine distance → similarity
                tags=json.loads(row[6]) if row[6] else [],
            ))
        return results

    def bm25_search(
        self,
        query_text: str,
        top_k: int = 10,
        tags: list[str] | None = None,
        folders: list[str] | None = None,
        after: str | None = None,
    ) -> list[SearchResult]:
        """BM25 search via FTS5 with optional pre-filtering on notes metadata."""
        # Build query with optional filters
        where_clauses = []
        params: list = []

        if tags:
            # Check if any of the note's tags match
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("n.tags LIKE ?")
                params.append(f'%"{tag}"%')
            where_clauses.append(f"({' OR '.join(tag_conditions)})")

        if folders:
            folder_conditions = []
            for folder in folders:
                folder_conditions.append("n.path LIKE ?")
                params.append(f"{folder}%")
            where_clauses.append(f"({' OR '.join(folder_conditions)})")

        if after:
            where_clauses.append("n.updated_at > ?")
            params.append(after)

        where_sql = ""
        if where_clauses:
            where_sql = "AND " + " AND ".join(where_clauses)

        query = f"""
            SELECT c.id, c.content, c.heading_path, n.path, n.title, n.tags,
                   bm25(chunks_fts) as rank
            FROM chunks_fts fts
            JOIN chunks c ON c.id = fts.rowid
            JOIN notes n ON n.id = c.note_id
            WHERE chunks_fts MATCH ?
            {where_sql}
            ORDER BY rank
            LIMIT ?
        """

        rows = self._conn.execute(
            query, [query_text] + params + [top_k]
        ).fetchall()

        results = []
        for row in rows:
            results.append(SearchResult(
                chunk_id=row[0],
                note_path=row[3],
                note_title=row[4],
                heading_path=row[2],
                content=row[1],
                score=abs(row[6]),  # bm25() returns negative values, lower = better
                tags=json.loads(row[5]) if row[5] else [],
            ))
        return results

    def get_all_chunk_embeddings_for_note(self, path: str) -> list[list[float]]:
        """Get all embeddings for chunks of a given note path."""
        rows = self._conn.execute(
            """SELECT cv.embedding
               FROM chunks_vec cv
               JOIN chunks c ON c.id = cv.chunk_id
               JOIN notes n ON n.id = c.note_id
               WHERE n.path = ?""",
            (path,),
        ).fetchall()

        embeddings = []
        for row in rows:
            blob = row[0]
            n_floats = len(blob) // 4
            vec = list(struct.unpack(f"{n_floats}f", blob))
            embeddings.append(vec)
        return embeddings

    def get_stats(self, embedding_model: str = "") -> IndexStats:
        """Get index statistics."""
        total_notes = self._conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        total_chunks = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        last_row = self._conn.execute(
            "SELECT MAX(updated_at) FROM notes"
        ).fetchone()
        last_indexed = last_row[0] if last_row else None

        db_size = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0.0

        return IndexStats(
            total_notes=total_notes,
            total_chunks=total_chunks,
            last_indexed=last_indexed,
            embedding_model=embedding_model,
            db_size_mb=round(db_size, 2),
        )

    def get_all_note_paths(self) -> list[str]:
        """Get all indexed note paths."""
        rows = self._conn.execute("SELECT path FROM notes").fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._conn.close()
