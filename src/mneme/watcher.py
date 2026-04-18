"""File watcher for the Mneme vault — reacts to .md changes and triggers indexing."""

from __future__ import annotations

import fnmatch
import logging
import threading
from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class _VaultEventHandler(FileSystemEventHandler):
    """Internal watchdog handler that filters events and delegates to the indexer."""

    def __init__(
        self,
        vault_path: Path,
        indexer,
        exclude_patterns: list[str],
        debounce_delay: float = 2.0,
        on_graph_change=None,
    ) -> None:
        super().__init__()
        self._vault_path = vault_path
        self._indexer = indexer
        self._exclude_patterns = exclude_patterns
        self._debounce_delay = debounce_delay
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        # Called after any write that may have changed the wikilink graph.
        # Used to invalidate SearchEngine's centrality cache so GARS doesn't
        # serve stale scores after live edits. Optional — None = no callback.
        self._on_graph_change = on_graph_change

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_md(self, path: str) -> bool:
        return path.endswith(".md")

    def _relative(self, abs_path: str) -> str:
        """Return forward-slash relative path from vault root."""
        try:
            rel = Path(abs_path).relative_to(self._vault_path)
        except ValueError:
            return abs_path
        return rel.as_posix()

    def _is_excluded(self, rel_path: str) -> bool:
        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        return False

    def _should_process(self, abs_path: str) -> bool:
        if not self._is_md(abs_path):
            return False
        rel = self._relative(abs_path)
        if self._is_excluded(rel):
            return False
        return True

    # ------------------------------------------------------------------
    # Debouncing
    # ------------------------------------------------------------------

    def _schedule(self, key: str, action) -> None:
        """Schedule *action* with debounce; cancel any existing timer for *key*."""
        with self._lock:
            existing = self._pending.pop(key, None)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(self._debounce_delay, self._fire, args=(key, action))
            self._pending[key] = timer
            timer.daemon = True
            timer.start()

    def _fire(self, key: str, action) -> None:
        with self._lock:
            self._pending.pop(key, None)
        action()
        if self._on_graph_change is not None:
            try:
                self._on_graph_change()
            except Exception as e:  # pragma: no cover — callback must never kill the watcher
                logger.debug("on_graph_change callback failed: %s", e)

    def cancel_all(self) -> None:
        """Cancel all pending debounce timers."""
        with self._lock:
            for timer in self._pending.values():
                timer.cancel()
            self._pending.clear()

    # ------------------------------------------------------------------
    # watchdog callbacks
    # ------------------------------------------------------------------

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        abs_path: str = event.src_path
        if not self._should_process(abs_path):
            return
        path = Path(abs_path)
        logger.debug("Created: %s", path)
        self._schedule(abs_path, lambda p=path: self._indexer.index_file(p))

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.is_directory:
            return
        abs_path: str = event.src_path
        if not self._should_process(abs_path):
            return
        path = Path(abs_path)
        logger.debug("Modified: %s", path)
        self._schedule(abs_path, lambda p=path: self._indexer.index_file(p))

    def on_deleted(self, event: FileDeletedEvent) -> None:
        if event.is_directory:
            return
        abs_path: str = event.src_path
        if not self._should_process(abs_path):
            return
        rel = self._relative(abs_path)
        logger.debug("Deleted: %s", rel)
        # No debouncing for deletes — execute immediately.
        self._indexer.remove_file(rel)
        if self._on_graph_change is not None:
            try:
                self._on_graph_change()
            except Exception as e:
                logger.debug("on_graph_change callback failed: %s", e)

    def on_moved(self, event: FileMovedEvent) -> None:
        if event.is_directory:
            return
        src: str = event.src_path
        dest: str = event.dest_path

        src_is_md = self._should_process(src)
        dest_is_md = self._should_process(dest)

        graph_changed = False
        if src_is_md:
            src_rel = self._relative(src)
            logger.debug("Moved (src removed): %s", src_rel)
            self._indexer.remove_file(src_rel)
            graph_changed = True

        if dest_is_md:
            dest_path = Path(dest)
            logger.debug("Moved (dest indexed): %s", dest_path)
            self._schedule(dest, lambda p=dest_path: self._indexer.index_file(p))
            # _schedule fires the on_graph_change itself after the debounce
            # runs; don't double-fire it here for the dest.

        if graph_changed and not dest_is_md and self._on_graph_change is not None:
            try:
                self._on_graph_change()
            except Exception as e:
                logger.debug("on_graph_change callback failed: %s", e)


class VaultWatcher:
    """Watches *vault_path* for .md file changes and keeps the indexer in sync."""

    def __init__(
        self,
        vault_path: Path,
        indexer,
        config,
        debounce_delay: float = 2.0,
        on_graph_change=None,
    ) -> None:
        self._vault_path = vault_path
        self._indexer = indexer
        self._exclude_patterns: list[str] = config.vault.exclude_patterns
        self._debounce_delay = debounce_delay
        self._on_graph_change = on_graph_change
        self._observer: Observer | None = None
        self._handler: _VaultEventHandler | None = None

    def start(self) -> None:
        """Start the watchdog observer."""
        if self._observer is not None:
            logger.warning("VaultWatcher already running — ignoring start()")
            return

        self._handler = _VaultEventHandler(
            vault_path=self._vault_path,
            indexer=self._indexer,
            exclude_patterns=self._exclude_patterns,
            debounce_delay=self._debounce_delay,
            on_graph_change=self._on_graph_change,
        )
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self._vault_path), recursive=True)
        self._observer.start()
        logger.info("VaultWatcher started on %s", self._vault_path)

    def stop(self) -> None:
        """Stop the observer and cancel all pending debounce timers."""
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join()
        self._observer = None

        if self._handler is not None:
            self._handler.cancel_all()
            self._handler = None

        logger.info("VaultWatcher stopped")
