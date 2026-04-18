"""Tests for mneme.paths.normalize_vault_path.

This function is the guard clause for vault-relative paths received via
MCP tool calls (get_similar, get_note_context) — it must reject any input
that could reach outside the vault or confuse downstream code. Previously
only exercised incidentally through test_server.py; these tests cover the
guard clauses directly.
"""

from __future__ import annotations

import pytest

from mneme.paths import normalize_vault_path


# ---------------------------------------------------------------------------
# Valid inputs — must be returned with backslashes normalized to /
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "input_path,expected",
    [
        ("note.md", "note.md"),
        ("folder/note.md", "folder/note.md"),
        ("folder\\note.md", "folder/note.md"),
        ("02 Projekte/Argus.md", "02 Projekte/Argus.md"),
        ("deep/nested/path/note.md", "deep/nested/path/note.md"),
        ("  folder/note.md  ", "folder/note.md"),  # stripped
        ("Umlaute/Über mich.md", "Umlaute/Über mich.md"),
        ("日本語.md", "日本語.md"),
        ("note with spaces.md", "note with spaces.md"),
    ],
)
def test_valid_paths(input_path: str, expected: str) -> None:
    assert normalize_vault_path(input_path) == expected


# ---------------------------------------------------------------------------
# Absolute paths must be rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",
        "/absolute/path.md",
        "C:/Windows/System32",
        "C:\\Windows\\System32",
        "D:/vault/note.md",
        "c:/lowercase/drive.md",
    ],
)
def test_absolute_paths_rejected(bad_path: str) -> None:
    assert normalize_vault_path(bad_path) is None


# ---------------------------------------------------------------------------
# Traversal (`..`) must be rejected anywhere in the path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "traversal",
    [
        "../secret.md",
        "../../secret.md",
        "folder/../../../etc/passwd",
        "foo/../bar.md",
        "foo/bar/../baz.md",
        "..",
        "..\\backslash.md",
    ],
)
def test_traversal_rejected(traversal: str) -> None:
    assert normalize_vault_path(traversal) is None


# ---------------------------------------------------------------------------
# Empty / type-invalid input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_input",
    [
        "",
        "   ",
        "\t\n",
    ],
)
def test_empty_input_rejected(bad_input: str) -> None:
    assert normalize_vault_path(bad_input) is None


def test_non_string_rejected() -> None:
    # Guard clause rejects non-strings without raising.
    assert normalize_vault_path(None) is None  # type: ignore[arg-type]
    assert normalize_vault_path(123) is None  # type: ignore[arg-type]
    assert normalize_vault_path([]) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Edge case: paths that look-almost-but-not-quite-like traversal
# ---------------------------------------------------------------------------

def test_double_dot_in_filename_allowed() -> None:
    """A file called `..backup.md` is not traversal — `..` must be a full path component."""
    assert normalize_vault_path("..backup.md") == "..backup.md"
    assert normalize_vault_path("folder/..backup.md") == "folder/..backup.md"
    assert normalize_vault_path("note..draft.md") == "note..draft.md"


def test_single_dot_allowed() -> None:
    """A single `.` is not traversal and is technically the current dir."""
    # Current implementation doesn't reject this — documented behavior.
    assert normalize_vault_path("./note.md") == "./note.md"
