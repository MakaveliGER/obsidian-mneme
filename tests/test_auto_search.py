"""Tests for mneme.auto_search — CLAUDE.md injection and hook installation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mneme.auto_search import (
    CLAUDE_MD_BLOCK,
    CLAUDE_MD_MARKER_END,
    CLAUDE_MD_MARKER_START,
    apply_mode,
    inject_claude_md,
    install_hooks,
    remove_claude_md,
    remove_hooks,
)
from mneme.config import AutoSearchConfig


# ---------------------------------------------------------------------------
# inject_claude_md
# ---------------------------------------------------------------------------

class TestInjectClaudeMd:
    def test_inject_claude_md_creates_file(self, tmp_path: Path):
        """File doesn't exist → created with block."""
        changed = inject_claude_md(tmp_path)
        assert changed is True

        target = tmp_path / "CLAUDE.md"
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert CLAUDE_MD_MARKER_START in content
        assert CLAUDE_MD_MARKER_END in content

    def test_inject_claude_md_appends_to_existing(self, tmp_path: Path):
        """Existing CLAUDE.md without block → block appended at end."""
        target = tmp_path / "CLAUDE.md"
        original_content = "# My Notes\n\nSome existing content.\n"
        target.write_text(original_content, encoding="utf-8")

        changed = inject_claude_md(tmp_path)
        assert changed is True

        content = target.read_text(encoding="utf-8")
        # Original content still present
        assert "# My Notes" in content
        assert "Some existing content." in content
        # Block appended after original content
        assert content.index("# My Notes") < content.index(CLAUDE_MD_MARKER_START)
        assert CLAUDE_MD_MARKER_END in content

    def test_inject_claude_md_idempotent(self, tmp_path: Path):
        """Block already present → no change, returns False."""
        target = tmp_path / "CLAUDE.md"
        target.write_text(CLAUDE_MD_BLOCK + "\n", encoding="utf-8")

        changed = inject_claude_md(tmp_path)
        assert changed is False

        # Content unchanged
        content = target.read_text(encoding="utf-8")
        assert content.count(CLAUDE_MD_MARKER_START) == 1


# ---------------------------------------------------------------------------
# remove_claude_md
# ---------------------------------------------------------------------------

class TestRemoveClaudeMd:
    def test_remove_claude_md(self, tmp_path: Path):
        """Block is removed, surrounding content preserved."""
        target = tmp_path / "CLAUDE.md"
        target.write_text(
            "# Notes\n\nSome content.\n\n" + CLAUDE_MD_BLOCK + "\n",
            encoding="utf-8",
        )

        changed = remove_claude_md(tmp_path)
        assert changed is True

        content = target.read_text(encoding="utf-8")
        assert CLAUDE_MD_MARKER_START not in content
        assert CLAUDE_MD_MARKER_END not in content
        assert "# Notes" in content
        assert "Some content." in content

    def test_remove_claude_md_no_block(self, tmp_path: Path):
        """No block present → no change, returns False."""
        target = tmp_path / "CLAUDE.md"
        original = "# Notes\n\nContent only.\n"
        target.write_text(original, encoding="utf-8")

        changed = remove_claude_md(tmp_path)
        assert changed is False

        assert target.read_text(encoding="utf-8") == original

    def test_remove_claude_md_nonexistent_file(self, tmp_path: Path):
        """File doesn't exist → returns False, no error."""
        changed = remove_claude_md(tmp_path)
        assert changed is False


# ---------------------------------------------------------------------------
# install_hooks
# ---------------------------------------------------------------------------

class TestInstallHooks:
    def test_install_hooks_creates_settings(self, tmp_path: Path):
        """No settings.local.json → created with hook entries."""
        (tmp_path / ".claude").mkdir()

        changed = install_hooks(tmp_path, ["Read"])
        assert changed is True

        settings_path = tmp_path / ".claude" / "settings.local.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = data["hooks"]["PreToolUse"]
        commands = [
            h.get("command", "")
            for e in entries
            for h in e.get("hooks", [e])
        ]
        assert any("mneme hook-search" in c for c in commands)

    def test_install_hooks_merges(self, tmp_path: Path):
        """Existing hooks preserved, Mneme hook added."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.local.json"
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
        settings_path.write_text(json.dumps(existing), encoding="utf-8")

        changed = install_hooks(tmp_path, ["Read"])
        assert changed is True

        data = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = data["hooks"]["PreToolUse"]
        commands = [
            h.get("command", "")
            for e in entries
            for h in e.get("hooks", [e])
        ]
        assert "other-tool" in commands
        assert any("mneme hook-search" in c for c in commands)

    def test_install_hooks_no_duplicate(self, tmp_path: Path):
        """Mneme hook already present → not added again."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.local.json"

        # Install once
        install_hooks(tmp_path, ["Read"])

        # Install again
        changed = install_hooks(tmp_path, ["Read"])
        assert changed is False

        data = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = data["hooks"]["PreToolUse"]
        count = sum(
            1
            for e in entries
            for h in e.get("hooks", [e])
            if "mneme hook-search" in h.get("command", "")
        )
        assert count == 1

    def test_install_hooks_grow_matchers_adds_new_entries(self, tmp_path: Path):
        """Regression (Codex 2026-04-19 Medium): the original dedup-by-command
        logic locked the matcher set after the first install. Going from
        ['Read'] to ['Read','Bash'] must actually install Bash."""
        install_hooks(tmp_path, ["Read"])
        changed = install_hooks(tmp_path, ["Read", "Bash"])
        assert changed is True, "Grow must be detected as a change"

        data = json.loads(
            (tmp_path / ".claude" / "settings.local.json").read_text(
                encoding="utf-8"
            )
        )
        matchers = [e.get("matcher") for e in data["hooks"]["PreToolUse"]]
        assert matchers == ["Read", "Bash"]

    def test_install_hooks_shrink_matchers_removes_entries(self, tmp_path: Path):
        """Shrinking the matcher list removes the dropped Mneme entry."""
        install_hooks(tmp_path, ["Read", "Bash"])
        changed = install_hooks(tmp_path, ["Read"])
        assert changed is True

        data = json.loads(
            (tmp_path / ".claude" / "settings.local.json").read_text(
                encoding="utf-8"
            )
        )
        matchers = [e.get("matcher") for e in data["hooks"]["PreToolUse"]]
        assert matchers == ["Read"]

    def test_install_hooks_preserves_non_mneme_entries(self, tmp_path: Path):
        """User-owned hooks in PreToolUse must survive a Mneme reconcile."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.local.json"
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Edit",
                                "hooks": [
                                    {"type": "command", "command": "user-tool-xyz"}
                                ],
                            }
                        ]
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        install_hooks(tmp_path, ["Read"])
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        commands = [
            h["command"]
            for e in data["hooks"]["PreToolUse"]
            for h in e.get("hooks", [])
        ]
        assert "user-tool-xyz" in commands
        assert "mneme hook-search" in commands

    def test_install_hooks_creates_dot_claude_dir(self, tmp_path: Path):
        """.claude directory doesn't exist → created automatically."""
        assert not (tmp_path / ".claude").exists()

        changed = install_hooks(tmp_path, ["Read"])
        assert changed is True
        assert (tmp_path / ".claude" / "settings.local.json").exists()


# ---------------------------------------------------------------------------
# remove_hooks
# ---------------------------------------------------------------------------

class TestRemoveHooks:
    def test_remove_hooks(self, tmp_path: Path):
        """Mneme hook removed, other hooks preserved."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.local.json"
        data = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "other-tool"}],
                    },
                    {
                        "matcher": "Read",
                        "hooks": [{"type": "command", "command": "mneme hook-search", "timeout": 5}],
                    },
                ]
            }
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")

        changed = remove_hooks(tmp_path)
        assert changed is True

        result = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = result["hooks"]["PreToolUse"]
        commands = [
            h.get("command", "")
            for e in entries
            for h in e.get("hooks", [e])
        ]
        assert "other-tool" in commands
        assert not any("mneme hook-search" in c for c in commands)

    def test_remove_hooks_no_mneme_entry(self, tmp_path: Path):
        """No Mneme hooks present → returns False."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.local.json"
        data = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "other-tool"}],
                    }
                ]
            }
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")

        changed = remove_hooks(tmp_path)
        assert changed is False

    def test_remove_hooks_no_file(self, tmp_path: Path):
        """No settings file → returns False, no error."""
        (tmp_path / ".claude").mkdir()
        changed = remove_hooks(tmp_path)
        assert changed is False


# ---------------------------------------------------------------------------
# apply_mode
# ---------------------------------------------------------------------------

class TestApplyMode:
    def _make_config(self) -> AutoSearchConfig:
        return AutoSearchConfig()

    def test_apply_mode_off(self, tmp_path: Path):
        """Mode off: removes CLAUDE.md block and hooks."""
        config = self._make_config()

        # Prepare: inject block + hook first
        inject_claude_md(tmp_path, config.claude_md_path)
        (tmp_path / ".claude").mkdir()
        install_hooks(tmp_path, config.hook_matchers)

        result = apply_mode("off", tmp_path, config)
        assert result["mode"] == "off"
        assert result["claude_md_changed"] is True
        assert result["hooks_changed"] is True

        # Verify block gone
        target = tmp_path / config.claude_md_path
        assert CLAUDE_MD_MARKER_START not in target.read_text(encoding="utf-8")

        # Verify hooks gone
        settings_path = tmp_path / ".claude" / "settings.local.json"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = data.get("hooks", {}).get("PreToolUse", [])
        commands = [
            h.get("command", "")
            for e in entries
            for h in e.get("hooks", [e])
        ]
        assert not any("mneme hook-search" in c for c in commands)

    def test_apply_mode_smart(self, tmp_path: Path):
        """Mode smart: injects CLAUDE.md block, removes hooks."""
        config = self._make_config()
        (tmp_path / ".claude").mkdir()

        # Pre-install a hook so we can verify it's removed
        install_hooks(tmp_path, config.hook_matchers)

        result = apply_mode("smart", tmp_path, config)
        assert result["mode"] == "smart"
        assert result["claude_md_changed"] is True
        assert result["hooks_changed"] is True

        # CLAUDE.md block present
        target = tmp_path / config.claude_md_path
        assert CLAUDE_MD_MARKER_START in target.read_text(encoding="utf-8")

        # Hooks removed
        settings_path = tmp_path / ".claude" / "settings.local.json"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = data.get("hooks", {}).get("PreToolUse", [])
        commands = [
            h.get("command", "")
            for e in entries
            for h in e.get("hooks", [e])
        ]
        assert not any("mneme hook-search" in c for c in commands)

    def test_apply_mode_always(self, tmp_path: Path):
        """Mode always: injects CLAUDE.md block and installs hooks."""
        config = self._make_config()

        result = apply_mode("always", tmp_path, config)
        assert result["mode"] == "always"
        assert result["claude_md_changed"] is True
        assert result["hooks_changed"] is True

        # CLAUDE.md block present
        target = tmp_path / config.claude_md_path
        assert CLAUDE_MD_MARKER_START in target.read_text(encoding="utf-8")

        # Hooks installed
        settings_path = tmp_path / ".claude" / "settings.local.json"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = data["hooks"]["PreToolUse"]
        commands = [
            h.get("command", "")
            for e in entries
            for h in e.get("hooks", [e])
        ]
        assert any("mneme hook-search" in c for c in commands)
