"""Vault indexer — scans, parses, embeds, and stores Obsidian notes."""

from __future__ import annotations

import fnmatch
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from mneme.config import MnemeConfig

logger = logging.getLogger(__name__)
from mneme.embeddings.base import EmbeddingProvider
from mneme.parser import chunk_note, parse_note
from mneme.store import ChunkData, Store

@dataclass
class IndexResult:
    indexed: int
    skipped: int
    deleted: int
    duration_seconds: float
    links_resolved: int = 0


class Indexer:
    def __init__(
        self,
        store: Store,
        embedding_provider: EmbeddingProvider,
        config: MnemeConfig,
    ) -> None:
        self._store = store
        self._embedding = embedding_provider
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_vault(
        self, full: bool = False, progress_callback=None
    ) -> IndexResult:
        """Scan the vault and index all matching notes.

        Args:
            full: When True, re-index every note regardless of hash.
                  When False (incremental), skip unchanged notes.
            progress_callback: Optional callable ``(current, total, path)``
                invoked after each file is processed. Used by the CLI to
                render a progress bar — matters on first-run full reindex
                which can take 15-25 min on CPU.

        Returns:
            IndexResult with counts and elapsed time.
        """
        start = time.monotonic()
        vault_root = self._config.vault_path
        glob_patterns = self._config.vault.glob_patterns or ["**/*.md"]
        exclude_patterns = self._config.vault.exclude_patterns or []

        # --- Collect all matching files ---
        found_files: list[Path] = []
        for pattern in glob_patterns:
            for file_path in vault_root.glob(pattern):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(vault_root).as_posix()
                if self._is_excluded(rel, exclude_patterns):
                    continue
                found_files.append(file_path)

        # Deduplicate while preserving order
        seen: set[Path] = set()
        unique_files: list[Path] = []
        for f in found_files:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)

        indexed = 0
        skipped = 0
        errors = 0
        vault_paths: set[str] = set()
        notes_for_link_resolution: list[tuple[int, list[str]]] = []

        # Batch-load all hashes for incremental mode (avoids N separate SELECTs)
        hash_cache: dict[str, tuple[int, str, list[str]]] = {}
        if not full:
            hash_cache = self._store.get_hash_cache()

        total = len(unique_files)
        for i, file_path in enumerate(unique_files, start=1):
            try:
                parsed = parse_note(file_path, vault_root)
            except Exception as e:
                logger.warning("Skipping %s: %s", file_path, e)
                errors += 1
                if progress_callback is not None:
                    progress_callback(i, total, str(file_path))
                continue

            vault_paths.add(parsed.path)

            if not full:
                cached = hash_cache.get(parsed.path)
                if cached and cached[1] == parsed.content_hash:
                    skipped += 1
                    notes_for_link_resolution.append((cached[0], cached[2]))
                    if progress_callback is not None:
                        progress_callback(i, total, parsed.path)
                    continue

            note_id = self._index_parsed(parsed)
            notes_for_link_resolution.append((note_id, parsed.wikilinks))
            indexed += 1
            if progress_callback is not None:
                progress_callback(i, total, parsed.path)

        # --- Remove orphaned notes ---
        db_paths = set(self._store.get_all_note_paths())
        orphaned = db_paths - vault_paths
        for orphan_path in orphaned:
            self._store.delete_note(orphan_path)
        deleted = len(orphaned)

        # --- Build wikilink graph (second pass after all notes are in DB) ---
        alias_map = self._store.build_alias_map()
        links_resolved = 0
        for note_id, wikilinks in notes_for_link_resolution:
            links_resolved += self._store.resolve_and_store_links(note_id, wikilinks, alias_map)

        duration = time.monotonic() - start
        return IndexResult(
            indexed=indexed,
            skipped=skipped,
            deleted=deleted,
            duration_seconds=duration,
            links_resolved=links_resolved,
        )

    def index_file(self, file_path: Path) -> bool:
        """Index a single file (e.g. triggered by a file watcher).

        Returns:
            True if the file was (re-)indexed, False if it was unchanged.
        """
        if not file_path.exists():
            return False

        vault_root = self._config.vault_path
        try:
            parsed = parse_note(file_path, vault_root)
        except Exception as e:
            logger.warning("Skipping %s: %s", file_path, e)
            return False

        existing = self._store.get_note_by_path(parsed.path)
        if existing and existing["content_hash"] == parsed.content_hash:
            return False

        note_id = self._index_parsed(parsed)
        alias_map = self._store.build_alias_map()
        self._store.resolve_and_store_links(note_id, parsed.wikilinks, alias_map)
        return True

    def remove_file(self, path: str) -> bool:
        """Remove a note from the index by its vault-relative path.

        Returns:
            True if the note existed and was deleted, False otherwise.
        """
        return self._store.delete_note(path)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _is_excluded(rel_posix: str, exclude_patterns: list[str]) -> bool:
        """Return True if the relative path matches any exclude pattern."""
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(rel_posix, pattern):
                return True
            normalized = pattern.rstrip("*").rstrip("/")
            if normalized and rel_posix.startswith(normalized + "/"):
                return True
        return False

    def _index_parsed(self, parsed) -> int:
        """Chunk, embed, and persist a single ParsedNote. Returns note_id."""
        chunks = chunk_note(
            parsed,
            self._config.chunking.max_tokens,
            self._config.chunking.overlap_tokens,
        )

        # Embed in batches (batch_size from config, default 32)
        chunk_texts = [c.content for c in chunks]
        batch_size = self._config.embedding.batch_size
        embeddings: list[list[float]] = []
        for i in range(0, len(chunk_texts), batch_size):
            batch = chunk_texts[i : i + batch_size]
            embeddings.extend(self._embedding.embed(batch))

        chunk_data = [
            ChunkData(
                content=chunk.content,
                heading_path=chunk.heading_path,
                chunk_index=chunk.chunk_index,
                embedding=emb,
            )
            for chunk, emb in zip(chunks, embeddings)
        ]

        note_id = self._store.upsert_note(
            path=parsed.path,
            title=parsed.title,
            content_hash=parsed.content_hash,
            frontmatter=parsed.frontmatter,
            tags=parsed.tags,
            wikilinks=parsed.wikilinks,
        )
        self._store.upsert_chunks(note_id, chunk_data)
        return note_id
