"""SQLite store with sqlite-vec (vectors) and FTS5 (BM25 keyword search)."""

from __future__ import annotations

import json
import logging
import sqlite3
import struct
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


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


CURRENT_SCHEMA_VERSION = 2


class MnemeSchemaError(RuntimeError):
    """Raised when the DB schema doesn't match the running Mneme version."""


class Store:
    def __init__(
        self,
        db_path: Path,
        embedding_dim: int,
        skip_version_check: bool = False,
    ) -> None:
        self.db_path = db_path
        self.embedding_dim = embedding_dim
        self._lock = threading.Lock()
        self._alias_map_cache: dict[str, int] | None = None
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._load_extensions()
        self._create_schema()
        if not skip_version_check:
            self._verify_schema_version()

    def _load_extensions(self) -> None:
        try:
            self._conn.enable_load_extension(True)
            import sqlite_vec
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load sqlite-vec extension: {e}. "
                "Install sqlite-vec: pip install sqlite-vec"
            ) from e

    def _create_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS _meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

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

        # Wikilink graph (adjacency list)
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS links (
                source_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                target_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                PRIMARY KEY (source_id, target_id)
            );
            CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id);
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

    def _verify_schema_version(self) -> None:
        """Raise MnemeSchemaError if the DB schema version doesn't match.

        Fresh DBs (no notes yet) are initialized to CURRENT_SCHEMA_VERSION.
        Legacy DBs (data present but no version row) raise with a migration hint.
        """
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT value FROM _meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None:
            stored = int(row[0])
            if stored == CURRENT_SCHEMA_VERSION:
                return
            if stored < CURRENT_SCHEMA_VERSION:
                raise MnemeSchemaError(
                    f"DB schema is v{stored}, this Mneme needs v{CURRENT_SCHEMA_VERSION}. "
                    f"Run `mneme reindex --full` to migrate."
                )
            raise MnemeSchemaError(
                f"DB schema is v{stored}, newer than this Mneme (v{CURRENT_SCHEMA_VERSION}). "
                f"Upgrade Mneme or start with a fresh DB."
            )

        # No version row: fresh DB or legacy.
        notes_count = cur.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        if notes_count == 0:
            self.set_schema_version(CURRENT_SCHEMA_VERSION)
        else:
            raise MnemeSchemaError(
                f"Legacy DB detected ({notes_count} notes, no schema version). "
                f"Run `mneme reindex --full` to migrate to v{CURRENT_SCHEMA_VERSION}."
            )

    def set_schema_version(self, version: int) -> None:
        """Persist the schema version into the `_meta` table."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO _meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(version),),
            )
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
        with self._lock:
            # Alias map depends only on (id, path) — detect whether this is a
            # new insert and keep the cache valid for content-only updates.
            existing = self._conn.execute(
                "SELECT 1 FROM notes WHERE path = ?", (path,)
            ).fetchone()
            if existing is None:
                self._alias_map_cache = None

            self._conn.execute(
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
                    json.dumps(frontmatter, default=str),
                    json.dumps(tags),
                    json.dumps(wikilinks),
                    now,
                ),
            )
            row = self._conn.execute(
                "SELECT id FROM notes WHERE path = ?", (path,)
            ).fetchone()
            self._conn.commit()
        return row[0]

    def upsert_chunks(self, note_id: int, chunks: list[ChunkData]) -> None:
        """Delete old chunks for note_id, insert new ones with embeddings.

        Runs in a single transaction — crash-safe.
        """
        with self._lock:
            cur = self._conn.cursor()
            try:
                # chunks_vec is a sqlite-vec virtual table; IN (SELECT ...) is
                # planned as a full scan, so we delete by chunk_id via
                # executemany for a point-lookup per row.
                old_ids = [
                    (r[0],)
                    for r in cur.execute(
                        "SELECT id FROM chunks WHERE note_id = ?", (note_id,)
                    ).fetchall()
                ]
                if old_ids:
                    cur.executemany("DELETE FROM chunks_vec WHERE chunk_id = ?", old_ids)

                # Delete old chunks (triggers handle FTS5 cleanup)
                cur.execute("DELETE FROM chunks WHERE note_id = ?", (note_id,))

                if chunks:
                    # Bulk-insert chunks, then bulk-insert their vec rows.
                    cur.executemany(
                        """INSERT INTO chunks (note_id, content, heading_path, chunk_index)
                           VALUES (?, ?, ?, ?)""",
                        [(note_id, c.content, c.heading_path, c.chunk_index) for c in chunks],
                    )
                    # Join the new rowids back to embeddings by chunk_index so
                    # the order of the input `chunks` list never matters.
                    embedding_by_index = {c.chunk_index: c.embedding for c in chunks}
                    id_rows = cur.execute(
                        "SELECT id, chunk_index FROM chunks WHERE note_id = ?",
                        (note_id,),
                    ).fetchall()
                    cur.executemany(
                        "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                        [
                            (cid, _serialize_float_vec(embedding_by_index[ci]))
                            for cid, ci in id_rows
                        ],
                    )

                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def delete_note(self, path: str) -> bool:
        """Delete a note and all its chunks. Returns True if note existed."""
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute("SELECT id FROM notes WHERE path = ?", (path,)).fetchone()
            if not row:
                return False

            note_id = row[0]
            try:
                # chunks_vec virtual table: point-lookup per id (see upsert_chunks).
                old_ids = [
                    (r[0],)
                    for r in cur.execute(
                        "SELECT id FROM chunks WHERE note_id = ?", (note_id,)
                    ).fetchall()
                ]
                if old_ids:
                    cur.executemany("DELETE FROM chunks_vec WHERE chunk_id = ?", old_ids)
                cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))
                self._conn.commit()
                self._alias_map_cache = None
            except Exception:
                self._conn.rollback()
                raise
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

    @staticmethod
    def _sanitize_fts5_query(query: str) -> str:
        """Escape user query for FTS5 MATCH.

        FTS5 treats characters like - * : as operators. Wrapping each token
        in double quotes makes them literal search terms.
        E.g. 'KI-Consulting' → '"KI" "Consulting"' (OR semantics in FTS5).

        Length is capped to protect against pathological inputs that would
        expand into a huge OR-tree and hang FTS5.
        """
        import re
        # Cap input length before tokenization — a 100k-word query otherwise
        # expands to a 100k-OR FTS5 match that can hang the DB.
        capped = query[:1000]
        # Split on non-word characters, keep only non-empty tokens
        tokens = re.split(r"[^\w]+", capped)
        tokens = [t for t in tokens if t][:64]
        if not tokens:
            return '""'
        return " ".join(f'"{t}"' for t in tokens)

    def bm25_search(
        self,
        query_text: str,
        top_k: int = 10,
        tags: list[str] | None = None,
        folders: list[str] | None = None,
        after: str | None = None,
    ) -> list[SearchResult]:
        """BM25 search via FTS5 with optional pre-filtering on notes metadata."""
        safe_query = self._sanitize_fts5_query(query_text)

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
            query, [safe_query] + params + [top_k]
        ).fetchall()

        results = []
        for row in rows:
            results.append(SearchResult(
                chunk_id=row[0],
                note_path=row[3],
                note_title=row[4],
                heading_path=row[2],
                content=row[1],
                score=abs(row[6]),  # bm25() returns negative; abs() makes higher = better
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

    def get_updated_at_map(self, paths: list[str]) -> dict[str, str]:
        """Return a {path: updated_at} map for the given paths.

        Used by the search engine to apply an ``after`` cutoff to vector
        results (BM25 pre-filters in SQL, vector results need a post-filter).
        """
        if not paths:
            return {}
        placeholders = ",".join("?" * len(paths))
        rows = self._conn.execute(
            f"SELECT path, updated_at FROM notes WHERE path IN ({placeholders})",
            paths,
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_centrality_map(self) -> dict[str, float]:
        """Get normalized in-degree centrality for all notes.

        Returns dict mapping note_path to centrality in [0, 1].
        Most-linked note gets 1.0, no backlinks gets 0.0.
        """
        rows = self._conn.execute(
            """SELECT n.path, COUNT(l.source_id) as in_degree
               FROM notes n
               LEFT JOIN links l ON n.id = l.target_id
               GROUP BY n.id"""
        ).fetchall()

        if not rows:
            return {}

        max_degree = max(r[1] for r in rows)
        if max_degree == 0:
            return {r[0]: 0.0 for r in rows}

        return {r[0]: r[1] / max_degree for r in rows}

    def build_alias_map(self) -> dict[str, int]:
        """Build a map from wikilink target strings to note_ids.

        Keys are basename (without .md) and full path (without .md).
        Conflict rule: if two notes share the same basename, only full-path keys remain.

        Result is cached; invalidated when notes are added or deleted. Content
        updates to an existing note leave the cache valid.
        """
        if self._alias_map_cache is not None:
            return self._alias_map_cache
        rows = self._conn.execute("SELECT id, path FROM notes").fetchall()

        from collections import defaultdict
        from pathlib import PurePosixPath

        basename_to_ids: dict[str, list[int]] = defaultdict(list)
        full_path_map: dict[str, int] = {}

        for note_id, path in rows:
            # Normalize to forward slashes (wikilinks always use /)
            normalized = path.replace("\\", "/")
            full_key = normalized[:-3] if normalized.endswith(".md") else normalized
            full_path_map[full_key] = note_id
            base = PurePosixPath(normalized).stem
            basename_to_ids[base].append(note_id)

        alias_map: dict[str, int] = {}
        alias_map.update(full_path_map)

        for base, ids in basename_to_ids.items():
            if len(ids) == 1:
                alias_map[base] = ids[0]

        self._alias_map_cache = alias_map
        return alias_map

    def resolve_and_store_links(
        self, note_id: int, wikilinks: list[str], alias_map: dict[str, int]
    ) -> int:
        """Resolve wikilinks and write to links table. Returns resolved count."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM links WHERE source_id = ?", (note_id,))

            resolved = 0
            for wikilink in wikilinks:
                target_id = alias_map.get(wikilink)
                if target_id is not None and target_id != note_id:
                    cur.execute(
                        "INSERT OR IGNORE INTO links (source_id, target_id) VALUES (?, ?)",
                        (note_id, target_id),
                    )
                    resolved += 1

            self._conn.commit()
        return resolved

    def get_linked_notes(self, note_id: int) -> list[dict]:
        """Return outgoing links: notes that this note links to."""
        rows = self._conn.execute(
            """SELECT n.id, n.path, n.title FROM links l
               JOIN notes n ON n.id = l.target_id WHERE l.source_id = ?""",
            (note_id,),
        ).fetchall()
        return [{"id": r[0], "path": r[1], "title": r[2]} for r in rows]

    def get_backlinks(self, note_id: int) -> list[dict]:
        """Return incoming links: notes that link to this note."""
        rows = self._conn.execute(
            """SELECT n.id, n.path, n.title FROM links l
               JOIN notes n ON n.id = l.source_id WHERE l.target_id = ?""",
            (note_id,),
        ).fetchall()
        return [{"id": r[0], "path": r[1], "title": r[2]} for r in rows]

    def get_graph_neighbors(self, note_id: int, depth: int = 1) -> list[dict]:
        """Return all notes within `depth` hops (outgoing + incoming), deduplicated."""
        visited: dict[int, dict] = {}
        frontier: set[int] = {note_id}

        for _ in range(depth):
            next_frontier: set[int] = set()
            for current_id in frontier:
                for row in self._conn.execute(
                    "SELECT n.id, n.path, n.title FROM links l JOIN notes n ON n.id = l.target_id WHERE l.source_id = ?",
                    (current_id,),
                ).fetchall():
                    nid = row[0]
                    if nid != note_id and nid not in visited:
                        visited[nid] = {"id": row[0], "path": row[1], "title": row[2], "direction": "outgoing"}
                        next_frontier.add(nid)
                for row in self._conn.execute(
                    "SELECT n.id, n.path, n.title FROM links l JOIN notes n ON n.id = l.source_id WHERE l.target_id = ?",
                    (current_id,),
                ).fetchall():
                    nid = row[0]
                    if nid != note_id and nid not in visited:
                        visited[nid] = {"id": row[0], "path": row[1], "title": row[2], "direction": "incoming"}
                        next_frontier.add(nid)
            frontier = next_frontier

        return list(visited.values())

    def get_hash_cache(self) -> dict[str, tuple[int, str, list[str]]]:
        """Return {path: (id, content_hash, wikilinks)} for all notes."""
        import json
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, path, content_hash, wikilinks FROM notes"
            ).fetchall()
        result = {}
        for row in rows:
            wl = json.loads(row[3]) if row[3] else []
            result[row[1]] = (row[0], row[2], wl)
        return result

    def close(self) -> None:
        self._conn.close()
