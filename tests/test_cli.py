"""Tests for mneme.cli — Click CLI commands via CliRunner."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mneme.auto_search import CLAUDE_MD_MARKER_START, CLAUDE_MD_MARKER_END
from mneme.cli import main
from mneme.config import MnemeConfig, VaultConfig, AutoSearchConfig, save_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIM = 16


class MockProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for _ in texts:
            v = [random.gauss(0, 1) for _ in range(DIM)]
            n = math.sqrt(sum(x * x for x in v))
            vecs.append([x / n for x in v])
        return vecs

    def dimension(self) -> int:
        return DIM

    def warmup(self) -> None:
        pass


def create_test_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("## Test\n\nSome content.", encoding="utf-8")
    return vault


def make_config(vault: Path, db_path: Path) -> MnemeConfig:
    """Create a minimal MnemeConfig pointing at tmp locations."""
    return MnemeConfig(
        vault=VaultConfig(path=str(vault)),
        database={"path": str(db_path)},
    )


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

class TestSetup:
    def test_setup_creates_config(self, tmp_path: Path):
        """setup wizard: valid input → config file is written, exit 0."""
        vault = create_test_vault(tmp_path)
        config_file = tmp_path / "config.toml"

        mock_provider = MockProvider()

        # Minimal IndexResult stub
        index_result = MagicMock()
        index_result.indexed = 1
        index_result.duration_seconds = 0.1

        mock_indexer = MagicMock()
        mock_indexer.index_vault.return_value = index_result

        mock_store = MagicMock()
        mock_store.close = MagicMock()

        # get_provider, Store, Indexer are lazy-imported inside the command,
        # so we patch them at their definition modules, not at mneme.cli.
        with (
            patch("mneme.embeddings.get_provider", return_value=mock_provider),
            patch("mneme.store.Store", return_value=mock_store),
            patch("mneme.indexer.Indexer", return_value=mock_indexer),
            patch("mneme.config.config_path", return_value=config_file),
        ):
            runner = CliRunner()
            # Input lines: vault path, embedding model, transport choice
            result = runner.invoke(
                main,
                ["setup"],
                input=f"{vault}\nBAI/bge-m3\nstreamable-http\n",
            )

        assert result.exit_code == 0, result.output
        assert config_file.exists()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_shows_stats(self, tmp_path: Path):
        """status with a valid config → shows Notes: and Chunks: lines."""
        vault = create_test_vault(tmp_path)
        db_path = tmp_path / "mneme.db"
        config_file = tmp_path / "config.toml"

        config = make_config(vault, db_path)
        save_config(config, config_file)

        mock_provider = MockProvider()
        mock_stats = MagicMock()
        mock_stats.total_notes = 3
        mock_stats.total_chunks = 9
        mock_stats.embedding_model = "BAAI/bge-m3"
        mock_stats.db_size_mb = 0.1
        mock_stats.last_indexed = "2026-01-01T00:00:00"

        mock_store = MagicMock()
        mock_store.get_stats.return_value = mock_stats
        mock_store.close = MagicMock()

        with (
            patch("mneme.cli.load_config", return_value=config),
            patch("mneme.config.config_path", return_value=config_file),
            patch("mneme.embeddings.get_provider", return_value=mock_provider),
            patch("mneme.store.Store", return_value=mock_store),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["status"])

        assert result.exit_code == 0, result.output
        assert "Notes:" in result.output
        assert "Chunks:" in result.output

    def test_status_no_config(self, tmp_path: Path):
        """status without a configured vault → error message or non-zero exit."""
        empty_config = MnemeConfig()  # vault.path == ""

        with patch("mneme.cli.load_config", return_value=empty_config):
            runner = CliRunner()
            result = runner.invoke(main, ["status"])

        assert result.exit_code != 0 or "mneme setup" in result.output.lower()


# ---------------------------------------------------------------------------
# reindex
# ---------------------------------------------------------------------------

class TestReindex:
    def _run_reindex(self, tmp_path: Path, *, full: bool) -> str:
        vault = create_test_vault(tmp_path)
        db_path = tmp_path / "mneme.db"
        config = make_config(vault, db_path)

        mock_provider = MockProvider()

        index_result = MagicMock()
        index_result.indexed = 1 if full else 0
        index_result.skipped = 0 if full else 1
        index_result.deleted = 0
        index_result.duration_seconds = 0.05

        mock_indexer = MagicMock()
        mock_indexer.index_vault.return_value = index_result

        mock_store = MagicMock()
        mock_store.close = MagicMock()

        with (
            patch("mneme.cli.load_config", return_value=config),
            patch("mneme.embeddings.get_provider", return_value=mock_provider),
            patch("mneme.store.Store", return_value=mock_store),
            patch("mneme.indexer.Indexer", return_value=mock_indexer),
        ):
            runner = CliRunner()
            args = ["reindex", "--full"] if full else ["reindex"]
            result = runner.invoke(main, args)

        assert result.exit_code == 0, result.output
        return result.output

    def test_reindex_incremental(self, tmp_path: Path):
        """reindex without --full → 'Skipped' appears in output."""
        output = self._run_reindex(tmp_path, full=False)
        assert "Skipped" in output

    def test_reindex_full(self, tmp_path: Path):
        """reindex --full → 'Indexed' appears in output."""
        output = self._run_reindex(tmp_path, full=True)
        assert "Indexed" in output


# ---------------------------------------------------------------------------
# auto-search
# ---------------------------------------------------------------------------

class TestAutoSearch:
    def _make_config(self, tmp_path: Path) -> MnemeConfig:
        vault = create_test_vault(tmp_path)
        db_path = tmp_path / "mneme.db"
        return make_config(vault, db_path)

    def test_auto_search_smart(self, tmp_path: Path):
        """auto-search smart → CLAUDE.md is created with the marker block."""
        config = self._make_config(tmp_path)

        with patch("mneme.cli.load_config", return_value=config):
            with patch("mneme.cli.save_config"):
                runner = CliRunner()
                result = runner.invoke(main, ["auto-search", "smart"])

        assert result.exit_code == 0, result.output
        claude_md = Path(config.vault.path) / config.auto_search.claude_md_path
        assert claude_md.exists(), "CLAUDE.md was not created"
        content = claude_md.read_text(encoding="utf-8")
        assert CLAUDE_MD_MARKER_START in content
        assert CLAUDE_MD_MARKER_END in content

    def test_auto_search_off(self, tmp_path: Path):
        """auto-search off → CLAUDE.md marker block is removed."""
        config = self._make_config(tmp_path)
        vault_path = Path(config.vault.path)

        # Pre-create CLAUDE.md with the marker block
        from mneme.auto_search import CLAUDE_MD_BLOCK
        claude_md = vault_path / config.auto_search.claude_md_path
        claude_md.write_text(CLAUDE_MD_BLOCK + "\n", encoding="utf-8")

        with patch("mneme.cli.load_config", return_value=config):
            with patch("mneme.cli.save_config"):
                runner = CliRunner()
                result = runner.invoke(main, ["auto-search", "off"])

        assert result.exit_code == 0, result.output
        content = claude_md.read_text(encoding="utf-8")
        assert CLAUDE_MD_MARKER_START not in content
        assert CLAUDE_MD_MARKER_END not in content

    def test_auto_search_always(self, tmp_path: Path):
        """auto-search always → CLAUDE.md has block AND settings.local.json has hook."""
        config = self._make_config(tmp_path)
        vault_path = Path(config.vault.path)

        with patch("mneme.cli.load_config", return_value=config):
            with patch("mneme.cli.save_config"):
                runner = CliRunner()
                result = runner.invoke(main, ["auto-search", "always"])

        assert result.exit_code == 0, result.output

        # CLAUDE.md must contain the block
        claude_md = vault_path / config.auto_search.claude_md_path
        assert claude_md.exists()
        content = claude_md.read_text(encoding="utf-8")
        assert CLAUDE_MD_MARKER_START in content

        # Hook must be installed
        settings_path = vault_path / ".claude" / "settings.local.json"
        assert settings_path.exists(), "settings.local.json was not created"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = data.get("hooks", {}).get("PreToolUse", [])
        commands = [
            h.get("command", "")
            for e in entries
            for h in e.get("hooks", [e])
        ]
        assert any("mneme hook-search" in c for c in commands)

    def test_auto_search_idempotent(self, tmp_path: Path):
        """Running auto-search smart twice → no errors, marker appears exactly once."""
        config = self._make_config(tmp_path)

        with patch("mneme.cli.load_config", return_value=config):
            with patch("mneme.cli.save_config"):
                runner = CliRunner()
                result1 = runner.invoke(main, ["auto-search", "smart"])
                result2 = runner.invoke(main, ["auto-search", "smart"])

        assert result1.exit_code == 0, result1.output
        assert result2.exit_code == 0, result2.output

        claude_md = Path(config.vault.path) / config.auto_search.claude_md_path
        content = claude_md.read_text(encoding="utf-8")
        assert content.count(CLAUDE_MD_MARKER_START) == 1
        assert content.count(CLAUDE_MD_MARKER_END) == 1


# ---------------------------------------------------------------------------
# Internal helper (only for this module)
# ---------------------------------------------------------------------------

def _save_to(config: MnemeConfig, path: Path) -> Path:
    """Redirect save_config to a tmp path in tests."""
    from mneme.config import save_config as _real_save
    return _real_save(config, path)
