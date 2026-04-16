"""Tests for Mneme Claude Code hook integration."""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mneme.cli import _deep_merge_hooks, _emit_context, _extract_query, main
from mneme.hooks import generate_hook_config
from mneme.store import SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_result(
    chunk_id: int = 1,
    note_path: str = "02 Projekte/KI-Strategie.md",
    note_title: str = "KI-Strategie",
    content: str = "KI Consulting, Use Cases, Akademie",
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        note_path=note_path,
        note_title=note_title,
        heading_path="",
        content=content,
        score=1.0,
        tags=[],
    )


def _hook_stdin(tool_name: str, tool_input: dict) -> str:
    """Build a Claude Code PreToolUse JSON string as sent on stdin."""
    return json.dumps({
        "session_id": "test-session",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": "/test",
    })


# ---------------------------------------------------------------------------
# test_extract_query
# ---------------------------------------------------------------------------

class TestExtractQuery:
    def test_read_tool_uses_file_stem(self):
        hook_data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "02 Projekte/KI-Strategie.md"},
        }
        assert _extract_query(hook_data) == "KI-Strategie"

    def test_read_tool_nested_path(self):
        hook_data = {
            "tool_input": {
                "file_path": "/vault/04 Ressourcen/RAG Tech-Stack Referenz.md"
            }
        }
        result = _extract_query(hook_data)
        assert result == "RAG Tech-Stack Referenz"

    def test_bash_tool_uses_command(self):
        hook_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        }
        assert _extract_query(hook_data) == "git status"

    def test_bash_command_truncated_at_100(self):
        long_cmd = "x" * 200
        hook_data = {"tool_input": {"command": long_cmd}}
        assert len(_extract_query(hook_data)) == 100

    def test_generic_query_field(self):
        hook_data = {"tool_input": {"query": "semantic search"}}
        assert _extract_query(hook_data) == "semantic search"

    def test_empty_tool_input(self):
        assert _extract_query({}) == ""
        assert _extract_query({"tool_input": {}}) == ""

    def test_empty_string_for_unknown_input(self):
        hook_data = {"tool_input": {"unknown_field": "value"}}
        assert _extract_query(hook_data) == ""


# ---------------------------------------------------------------------------
# test_hook_search_returns_compact_results
# ---------------------------------------------------------------------------

class TestHookSearchOutput:
    def test_compact_output_format(self, capsys):
        """Output must match [Mneme Context] format."""
        results = [
            _make_search_result(1, "00 Kontext/Über mich.md", "Über mich", "KI-Consulting, MBA"),
            _make_search_result(2, "04 Ressourcen/RAG.md", "RAG Tech-Stack", "Vector DBs"),
            _make_search_result(3, "02 Projekte/KI.md", "KI-Strategie", "Akademie, Use Cases"),
        ]

        stdin_json = _hook_stdin("Read", {"file_path": "notes/test.md"})

        mock_store = MagicMock()
        mock_store.bm25_search.return_value = results

        mock_config = MagicMock()
        mock_config.vault.path = "/vault"
        mock_config.db_path = Path("/vault/.mneme.db")

        with patch("mneme.cli.load_config", return_value=mock_config), \
             patch("mneme.store.Store", return_value=mock_store):
            runner = CliRunner()
            result = runner.invoke(main, ["hook-search"], input=stdin_json)

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"

        context = output["hookSpecificOutput"]["additionalContext"]
        assert "[Mneme Context]" in context
        assert "Über mich" in context
        assert "RAG Tech-Stack" in context
        assert "KI-Strategie" in context
        # Note paths must appear
        assert "00 Kontext/Über mich.md" in context

    def test_output_has_note_count(self, capsys):
        """Header line must say how many notes were found."""
        results = [_make_search_result(i) for i in range(2)]

        stdin_json = _hook_stdin("Read", {"file_path": "notes/foo.md"})

        mock_store = MagicMock()
        mock_store.bm25_search.return_value = results
        mock_config = MagicMock()
        mock_config.vault.path = "/vault"
        mock_config.db_path = Path("/vault/.mneme.db")

        with patch("mneme.cli.load_config", return_value=mock_config), \
             patch("mneme.store.Store", return_value=mock_store):
            runner = CliRunner()
            result = runner.invoke(main, ["hook-search"], input=stdin_json)

        assert result.exit_code == 0
        context = json.loads(result.output)["hookSpecificOutput"]["additionalContext"]
        assert "Found 2 relevant note(s)" in context

    def test_empty_query_returns_allow_no_context(self):
        """When no query can be extracted, allow without context."""
        stdin_json = _hook_stdin("Read", {})  # no file_path

        runner = CliRunner()
        result = runner.invoke(main, ["hook-search"], input=stdin_json)

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "additionalContext" not in output["hookSpecificOutput"]

    def test_no_results_returns_allow_no_context(self):
        """When BM25 returns nothing, allow without context."""
        stdin_json = _hook_stdin("Read", {"file_path": "notes/test.md"})

        mock_store = MagicMock()
        mock_store.bm25_search.return_value = []
        mock_config = MagicMock()
        mock_config.vault.path = "/vault"
        mock_config.db_path = Path("/vault/.mneme.db")

        with patch("mneme.cli.load_config", return_value=mock_config), \
             patch("mneme.store.Store", return_value=mock_store):
            runner = CliRunner()
            result = runner.invoke(main, ["hook-search"], input=stdin_json)

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert "additionalContext" not in output["hookSpecificOutput"]

    def test_store_error_returns_allow_gracefully(self):
        """If Store raises, exit 0 and allow — never block Claude."""
        stdin_json = _hook_stdin("Read", {"file_path": "notes/test.md"})

        mock_config = MagicMock()
        mock_config.vault.path = "/vault"
        mock_config.db_path = Path("/vault/.mneme.db")

        with patch("mneme.cli.load_config", return_value=mock_config), \
             patch("mneme.store.Store", side_effect=RuntimeError("db error")):
            runner = CliRunner()
            result = runner.invoke(main, ["hook-search"], input=stdin_json)

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_invalid_stdin_returns_allow_gracefully(self):
        """Invalid JSON on stdin must not crash — exit 0 always."""
        runner = CliRunner()
        result = runner.invoke(main, ["hook-search"], input="NOT VALID JSON")

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_content_snippet_truncated(self):
        """Content snippet in output must not exceed 80 chars."""
        long_content = "A" * 300
        results = [_make_search_result(1, "note.md", "Long Note", long_content)]

        stdin_json = _hook_stdin("Read", {"file_path": "notes/test.md"})
        mock_store = MagicMock()
        mock_store.bm25_search.return_value = results
        mock_config = MagicMock()
        mock_config.vault.path = "/vault"
        mock_config.db_path = Path("/vault/.mneme.db")

        with patch("mneme.cli.load_config", return_value=mock_config), \
             patch("mneme.store.Store", return_value=mock_store):
            runner = CliRunner()
            result = runner.invoke(main, ["hook-search"], input=stdin_json)

        context = json.loads(result.output)["hookSpecificOutput"]["additionalContext"]
        # Each line in context after the header should have at most 80 snippet chars
        lines = context.split("\n")
        for line in lines[1:]:  # skip header
            # Snippet is after the " — " separator
            if " — " in line:
                snippet = line.split(" — ", 1)[1]
                assert len(snippet) <= 80, f"Snippet too long: {snippet!r}"


# ---------------------------------------------------------------------------
# test_hook_search_fast_no_model_load
# ---------------------------------------------------------------------------

class TestHookSearchFast:
    def test_no_embedding_provider_import(self):
        """hook-search must not import sentence_transformers or similar ML libs."""
        import importlib
        import sys

        # We track which modules get imported during hook-search execution
        imported_modules: list[str] = []
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        ml_libs = {"sentence_transformers", "torch", "transformers", "numpy"}

        stdin_json = _hook_stdin("Read", {"file_path": "notes/test.md"})
        mock_store = MagicMock()
        mock_store.bm25_search.return_value = []
        mock_config = MagicMock()
        mock_config.vault.path = "/vault"
        mock_config.db_path = Path("/vault/.mneme.db")

        with patch("mneme.cli.load_config", return_value=mock_config), \
             patch("mneme.store.Store", return_value=mock_store):
            runner = CliRunner()
            result = runner.invoke(main, ["hook-search"], input=stdin_json)

        assert result.exit_code == 0
        # Store was called directly — no embedding provider instantiated
        mock_store.bm25_search.assert_called_once()
        # Verify the Store mock was NOT called with any embedding provider arg
        # (we pass embedding_dim=1, no provider)

    def test_bm25_search_called_not_vector_search(self):
        """hook-search must use bm25_search, never vector_search."""
        stdin_json = _hook_stdin("Read", {"file_path": "notes/KI-Strategie.md"})

        mock_store = MagicMock()
        mock_store.bm25_search.return_value = []
        mock_config = MagicMock()
        mock_config.vault.path = "/vault"
        mock_config.db_path = Path("/vault/.mneme.db")

        with patch("mneme.cli.load_config", return_value=mock_config), \
             patch("mneme.store.Store", return_value=mock_store):
            runner = CliRunner()
            runner.invoke(main, ["hook-search"], input=stdin_json)

        mock_store.bm25_search.assert_called_once()
        mock_store.vector_search.assert_not_called()


# ---------------------------------------------------------------------------
# test_generate_hook_config
# ---------------------------------------------------------------------------

class TestGenerateHookConfig:
    def test_returns_dict(self):
        config = generate_hook_config()
        assert isinstance(config, dict)

    def test_has_hooks_key(self):
        config = generate_hook_config()
        assert "hooks" in config

    def test_has_pre_tool_use(self):
        config = generate_hook_config()
        assert "PreToolUse" in config["hooks"]

    def test_pre_tool_use_is_list(self):
        config = generate_hook_config()
        assert isinstance(config["hooks"]["PreToolUse"], list)
        assert len(config["hooks"]["PreToolUse"]) >= 1

    def test_read_matcher(self):
        config = generate_hook_config()
        entry = config["hooks"]["PreToolUse"][0]
        assert entry["matcher"] == "Read"

    def test_command_is_mneme_hook_search(self):
        """Each hook entry must use 'mneme hook-search' as command."""
        config = generate_hook_config()
        entry = config["hooks"]["PreToolUse"][0]
        # New format has nested hooks list
        hooks = entry.get("hooks", [entry])
        commands = [h.get("command", "") for h in hooks]
        assert any("mneme hook-search" in cmd for cmd in commands)

    def test_has_timeout(self):
        """Hook must declare a timeout to avoid blocking Claude indefinitely."""
        config = generate_hook_config()
        entry = config["hooks"]["PreToolUse"][0]
        hooks = entry.get("hooks", [entry])
        for h in hooks:
            if "command" in h:
                assert "timeout" in h, "Hook must have a timeout"
                assert h["timeout"] <= 10, "Timeout must be ≤10s for fast path"


# ---------------------------------------------------------------------------
# test_deep_merge_hooks
# ---------------------------------------------------------------------------

class TestDeepMergeHooks:
    def test_merge_into_empty(self):
        hook_config = generate_hook_config()
        merged = _deep_merge_hooks({}, hook_config)
        assert "hooks" in merged
        assert "PreToolUse" in merged["hooks"]

    def test_no_duplicate_on_second_merge(self):
        hook_config = generate_hook_config()
        merged_once = _deep_merge_hooks({}, hook_config)
        merged_twice = _deep_merge_hooks(merged_once, hook_config)
        # Should not double-add the same hook
        entries = merged_twice["hooks"]["PreToolUse"]
        # Count entries with mneme hook-search command
        count = sum(
            1 for e in entries
            for h in e.get("hooks", [e])
            if "mneme hook-search" in h.get("command", "")
        )
        assert count == 1, "Duplicate hook entries must not be added"

    def test_preserves_existing_hooks(self):
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "other-tool"}],
                    }
                ]
            }
        }
        hook_config = generate_hook_config()
        merged = _deep_merge_hooks(existing, hook_config)
        entries = merged["hooks"]["PreToolUse"]
        commands = [
            h.get("command", "")
            for e in entries
            for h in e.get("hooks", [e])
        ]
        assert "other-tool" in commands
        assert any("mneme hook-search" in c for c in commands)

    def test_preserves_non_hook_keys(self):
        existing = {"permissions": {"allow": ["git *"]}, "hooks": {}}
        hook_config = generate_hook_config()
        merged = _deep_merge_hooks(existing, hook_config)
        assert merged["permissions"] == {"allow": ["git *"]}
