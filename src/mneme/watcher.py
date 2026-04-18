"""File watcher for the Mneme vault — reacts to .md changes and triggers indexing."""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
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
    """Internal watchdog handler that filters events and delegates to the indexer.

    Uses a **global coalescing debounce**: events accumulate into a pending
    set, and a single timer fires once activity has quiesced for
    ``debounce_delay`` seconds. This coalesces bulk operations (Obsidian
    Sync pull, git merge, VS Code "Save All") into a single indexing pass
    instead of N serialized per-file reindexes, each holding the SQLite
    write lock while interactive search queries wait behind it.

    A ``max_defer`` cap prevents continuous-typing starvation: if the first
    pending event is older than max_defer, the batch fires even if events
    keep arriving. Deletes remain synchronous — we can't index a missing
    file anyway and a stale row in the DB is worse than a lock blip.
    """

    def __init__(
        self,
        vault_path: Path,
        indexer,
        exclude_patterns: list[str],
        debounce_delay: float = 2.0,
        on_graph_change=None,
        max_defer: float = 10.0,
    ) -> None:
        super().__init__()
        self._vault_path = vault_path
        self._indexer = indexer
        self._exclude_patterns = exclude_patterns
        self._debounce_delay = debounce_delay
        self._max_defer = max_defer
        # Global coalescing state — one timer, one pending-set.
        self._pending_paths: set[Path] = set()
        self._global_timer: threading.Timer | None = None
        self._first_event_at: float = 0.0
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
    # Debouncing — global coalescing
    # ------------------------------------------------------------------

    def _schedule(self, path: Path) -> None:
        """Add *path* to the pending batch and (re)arm the global timer.

        If no timer is running, start one. If one is running, cancel and
        reschedule — unless we've been accumulating longer than max_defer,
        in which case we let the existing timer fire to avoid starvation.
        """
        now = time.monotonic()
        should_fire_now = False
        with self._lock:
            self._pending_paths.add(path)
            if self._first_event_at == 0.0:
                self._first_event_at = now

            elapsed = now - self._first_event_at
            if elapsed >= self._max_defer:
                # Don't reset the timer — max-defer has been reached, just
                # let whatever is scheduled (or schedule-now) run soon.
                if self._global_timer is None:
                    should_fire_now = True
            else:
                # Normal case: reset the timer so quiet settles again.
                if self._global_timer is not None:
                    self._global_timer.cancel()
                timer = threading.Timer(self._debounce_delay, self._fire_batch)
                timer.daemon = True
                self._global_timer = timer
                timer.start()

        if should_fire_now:
            # Fire outside the lock (callbacks may re-enter).
            self._fire_batch()

    def _fire_batch(self) -> None:
        """Drain the pending set and index all paths in one pass."""
        with self._lock:
            paths = list(self._pending_paths)
            self._pending_paths.clear()
            self._first_event_at = 0.0
            self._global_timer = None

        if not paths:
            return

        # Index each file. For large batches this is still N sequential
        # index_file calls, but they all execute in one wake-up window
        # rather than being spread across N separate Timer threads that
        # each acquire the SQLite write lock independently. Search queries
        # wait once instead of up-to-N times.
        n_indexed = 0
        for path in paths:
            try:
                if self._indexer.index_file(path):
                    n_indexed += 1
            except Exception as e:  # pragma: no cover — keep the watcher alive
                logger.warning("index_file(%s) failed: %s", path, e)

        if n_indexed > 1:
            logger.info(
                "Watcher batch indexed %d files (from %d pending)",
                n_indexed, len(paths),
            )

        # One graph-change notification per batch, not per file.
        if self._on_graph_change is not None:
            try:
                self._on_graph_change()
            except Exception as e:  # pragma: no cover
                logger.debug("on_graph_change callback failed: %s", e)

    def cancel_all(self) -> None:
        """Cancel the global debounce timer and drop pending paths."""
        with self._lock:
            if self._global_timer is not None:
                self._global_timer.cancel()
                self._global_timer = None
            self._pending_paths.clear()
            self._first_event_at = 0.0

    # ------------------------------------------------------------------
    # watchdog callbacks
    # ------------------------------------------------------------------

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        abs_path: str = event.src_path
        if not self._should_process(abs_path):
            return
        logger.debug("Created: %s", abs_path)
        self._schedule(Path(abs_path))

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.is_directory:
            return
        abs_path: str = event.src_path
        if not self._should_process(abs_path):
            return
        logger.debug("Modified: %s", abs_path)
        self._schedule(Path(abs_path))

    def on_deleted(self, event: FileDeletedEvent) -> None:
        if event.is_directory:
            return
        abs_path: str = event.src_path
        if not self._should_process(abs_path):
            return
        rel = self._relative(abs_path)
        logger.debug("Deleted: %s", rel)
        # No debouncing for deletes — execute immediately. A deleted file
        # that stays in the index is worse than a brief lock blip.
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
            logger.debug("Moved (dest indexed): %s", dest)
            self._schedule(Path(dest))
            # _fire_batch fires on_graph_change itself; don't double-fire here.

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
