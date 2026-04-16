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
