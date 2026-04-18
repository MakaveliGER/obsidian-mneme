"""Tests for VaultWatcher (Block 9)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mneme.watcher import VaultWatcher

# ---------------------------------------------------------------------------
# Shared test config & fixtures
# ---------------------------------------------------------------------------

DEBOUNCE = 0.3  # seconds — fast enough for tests


class MockConfig:
    class vault:
        exclude_patterns = [".obsidian/**", ".trash/**"]


@pytest.fixture()
def vault_dir(tmp_path: Path) -> Path:
    """Temporary directory acting as the vault root."""
    return tmp_path


@pytest.fixture()
def indexer() -> MagicMock:
    mock = MagicMock()
    mock.index_file.return_value = True
    mock.remove_file.return_value = True
    return mock


@pytest.fixture()
def watcher(vault_dir: Path, indexer: MagicMock):
    """Start a VaultWatcher, yield it, then stop it."""
    w = VaultWatcher(vault_path=vault_dir, indexer=indexer, config=MockConfig(), debounce_delay=DEBOUNCE)
    w.start()
    yield w
    w.stop()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _settle(extra: float = 0.0) -> None:
    """Wait for watchdog event loop + debounce to settle."""
    time.sleep(DEBOUNCE + 0.2 + extra)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_md_file_created(watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock) -> None:
    """Creating a .md file should trigger indexer.index_file after debounce."""
    note = vault_dir / "hello.md"
    note.write_text("# Hello")
    _settle()
    indexer.index_file.assert_called_once_with(note)


def test_md_file_modified(watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock) -> None:
    """Modifying a .md file should trigger indexer.index_file."""
    note = vault_dir / "note.md"
    note.write_text("initial")
    _settle()
    indexer.index_file.reset_mock()

    note.write_text("updated content")
    _settle()
    indexer.index_file.assert_called_once_with(note)


def test_non_md_ignored(watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock) -> None:
    """Creating .txt or .json files must NOT trigger the indexer."""
    (vault_dir / "readme.txt").write_text("text")
    (vault_dir / "data.json").write_text("{}")
    _settle()
    indexer.index_file.assert_not_called()


def test_excluded_path_ignored(watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock) -> None:
    """Files inside excluded directories (e.g. .obsidian/) must be ignored."""
    obsidian_dir = vault_dir / ".obsidian"
    obsidian_dir.mkdir()
    (obsidian_dir / "workspace.md").write_text("internal")
    _settle()
    indexer.index_file.assert_not_called()


def test_file_deleted(watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock) -> None:
    """Deleting a .md file should immediately call indexer.remove_file with its relative path."""
    note = vault_dir / "to_delete.md"
    note.write_text("goodbye")
    _settle()
    indexer.index_file.reset_mock()

    note.unlink()
    # Delete is immediate — a short wait is sufficient.
    time.sleep(0.2)
    indexer.remove_file.assert_called_once_with("to_delete.md")


def test_debouncing(watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock) -> None:
    """Multiple rapid events for the same file should result in only one index_file call."""
    note = vault_dir / "rapid.md"
    note.write_text("v1")
    time.sleep(0.05)
    note.write_text("v2")
    time.sleep(0.05)
    note.write_text("v3")
    _settle()

    assert indexer.index_file.call_count == 1
    indexer.index_file.assert_called_with(note)


def test_file_moved(watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock) -> None:
    """Moving a .md file should remove the old path and index the new one."""
    src = vault_dir / "old_name.md"
    dest = vault_dir / "new_name.md"
    src.write_text("content")
    _settle()
    indexer.index_file.reset_mock()

    src.rename(dest)
    _settle()

    indexer.remove_file.assert_called_once_with("old_name.md")
    indexer.index_file.assert_called_once_with(dest)


def test_bulk_save_coalesces_into_single_batch(
    watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock
) -> None:
    """Bulk saving many files within the debounce window must fire ONE batch,
    not N separate callbacks serialized across N timers.

    Regression guard: the per-path-timer implementation serialized lock
    acquisitions and could stall interactive search queries for tens of
    seconds during Obsidian Sync pulls or git merges.
    """
    # Write 20 files rapidly — well within the DEBOUNCE window
    notes = []
    for i in range(20):
        note = vault_dir / f"bulk_{i}.md"
        note.write_text(f"content {i}")
        notes.append(note)

    # Give watchdog time to deliver events, then wait out debounce.
    _settle()

    # All 20 files must have been indexed (set-dedup inside batch).
    assert indexer.index_file.call_count == 20
    indexed_paths = {call.args[0] for call in indexer.index_file.call_args_list}
    assert indexed_paths == set(notes)


def test_bulk_save_dedups_duplicate_events(
    watcher: VaultWatcher, vault_dir: Path, indexer: MagicMock
) -> None:
    """If one file fires multiple events within the debounce window,
    it must still only be indexed once per batch."""
    note = vault_dir / "touched_many_times.md"
    # Rapid writes — should all coalesce into a single index_file call
    for content in ["a", "b", "c", "d", "e"]:
        note.write_text(content)
        time.sleep(0.02)
    _settle()

    assert indexer.index_file.call_count == 1
    indexer.index_file.assert_called_with(note)


def test_graph_change_callback_fires_once_per_batch(
    vault_dir: Path, indexer: MagicMock
) -> None:
    """on_graph_change must fire once for the whole batch, not per-file."""
    on_graph_change = MagicMock()
    w = VaultWatcher(
        vault_path=vault_dir,
        indexer=indexer,
        config=MockConfig(),
        debounce_delay=DEBOUNCE,
        on_graph_change=on_graph_change,
    )
    w.start()
    try:
        for i in range(5):
            (vault_dir / f"gc_{i}.md").write_text(f"v{i}")
        _settle()
    finally:
        w.stop()

    # 5 files in the batch → 5 index_file calls → ONE on_graph_change call
    assert indexer.index_file.call_count == 5
    assert on_graph_change.call_count == 1
