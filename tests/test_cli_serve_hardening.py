"""Tests for the security/UX guards in `mneme serve`.

These cover code paths added after the 11-hour MCP-hang session and the
subsequent 2-agent review: non-loopback bind guard, port-collision probe,
and offline-by-default env var toggles.
"""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mneme.cli import main


def _write_config(tmp_path: Path, transport: str = "streamable-http",
                  host: str = "127.0.0.1", port: int = 8765) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"""[vault]
path = "{tmp_path.as_posix()}"

[database]
path = "{(tmp_path / 'mneme.db').as_posix()}"

[server]
transport = "{transport}"
host = "{host}"
port = {port}
""",
        encoding="utf-8",
    )
    return cfg


class TestNonLoopbackGuard:
    def test_refuses_0_0_0_0_without_env_override(self, tmp_path: Path, monkeypatch):
        """Binding 0.0.0.0 without MNEME_ALLOW_NONLOOPBACK=1 must error out."""
        cfg = _write_config(tmp_path, host="0.0.0.0")
        monkeypatch.delenv("MNEME_ALLOW_NONLOOPBACK", raising=False)
        with patch("mneme.config.config_path", return_value=cfg):
            runner = CliRunner()
            result = runner.invoke(main, ["serve"])

        assert result.exit_code == 1
        assert "refusing to bind" in result.output or "refusing to bind" in (result.stderr or "")

    def test_env_override_allows_non_loopback(self, tmp_path: Path, monkeypatch):
        """MNEME_ALLOW_NONLOOPBACK=1 + explicit config must proceed past the guard.

        We don't let the server actually start — we patch create_server so the
        guard is the only thing exercised before the test returns.
        """
        cfg = _write_config(tmp_path, host="0.0.0.0", port=18765)
        monkeypatch.setenv("MNEME_ALLOW_NONLOOPBACK", "1")

        with patch("mneme.config.config_path", return_value=cfg), \
             patch("mneme.server.create_server") as mock_create, \
             patch("mneme.cli.click.echo"):
            mock_server = MagicMock()
            mock_create.return_value = mock_server
            runner = CliRunner()
            result = runner.invoke(main, ["serve"])

        # Non-loopback guard passed — server.run would have been called.
        # Exit code 0 or a normal startup path matters less than "didn't
        # error on the guard".
        mock_server.run.assert_called_once()


class TestPortCollisionProbe:
    def test_probe_rejects_bound_port(self, tmp_path: Path):
        """If another process holds the port, serve must exit with a clear error."""
        # Bind a socket to force collision
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            sock.bind(("127.0.0.1", 0))  # OS picks free port
            busy_port = sock.getsockname()[1]
            sock.listen(1)

            cfg = _write_config(tmp_path, port=busy_port)
            with patch("mneme.config.config_path", return_value=cfg):
                runner = CliRunner()
                result = runner.invoke(main, ["serve"])

            assert result.exit_code == 1
            # Error message should point the user at the remediation.
            combined = result.output + (result.stderr or "")
            assert str(busy_port) in combined or "already in use" in combined
        finally:
            sock.close()


class TestOfflineEnvVars:
    def test_offline_env_vars_set_by_default(self, tmp_path: Path, monkeypatch):
        """HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE must be set when MNEME_ALLOW_NETWORK != 1."""
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
        monkeypatch.delenv("MNEME_ALLOW_NETWORK", raising=False)

        cfg = _write_config(tmp_path, transport="stdio")  # skip HTTP guards
        # Patch before running — we abort before server.run()
        with patch("mneme.config.config_path", return_value=cfg), \
             patch("mneme.server.create_server") as mock_create:
            mock_server = MagicMock()
            mock_server.run.side_effect = SystemExit(0)  # abort cleanly
            mock_create.return_value = mock_server
            runner = CliRunner()
            runner.invoke(main, ["serve"])

        import os
        assert os.environ.get("HF_HUB_OFFLINE") == "1"
        assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"

    def test_mneme_allow_network_skips_offline(self, tmp_path: Path, monkeypatch):
        """MNEME_ALLOW_NETWORK=1 must leave HF_HUB_OFFLINE unset."""
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
        monkeypatch.setenv("MNEME_ALLOW_NETWORK", "1")

        cfg = _write_config(tmp_path, transport="stdio")
        with patch("mneme.config.config_path", return_value=cfg), \
             patch("mneme.server.create_server") as mock_create:
            mock_server = MagicMock()
            mock_server.run.side_effect = SystemExit(0)
            mock_create.return_value = mock_server
            runner = CliRunner()
            runner.invoke(main, ["serve"])

        import os
        assert os.environ.get("HF_HUB_OFFLINE") != "1"
        assert os.environ.get("TRANSFORMERS_OFFLINE") != "1"


class TestSetupPersistsTransport:
    def test_setup_saves_transport_choice(self, tmp_path: Path):
        """Regression: test_setup_creates_config sent transport input but
        didn't assert the saved config held the chosen value. Close that gap.
        """
        config_file = tmp_path / "config.toml"
        vault = tmp_path / "vault"
        vault.mkdir()

        mock_provider = MagicMock()
        mock_provider.dimension.return_value = 16

        index_result = MagicMock()
        index_result.indexed = 0
        index_result.duration_seconds = 0.0

        mock_indexer = MagicMock()
        mock_indexer.index_vault.return_value = index_result

        mock_store = MagicMock()

        with patch("mneme.embeddings.get_provider", return_value=mock_provider), \
             patch("mneme.store.Store", return_value=mock_store), \
             patch("mneme.indexer.Indexer", return_value=mock_indexer), \
             patch("mneme.config.config_path", return_value=config_file):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["setup"],
                input=f"{vault}\nBAAI/bge-m3\nstreamable-http\n",
            )

        assert result.exit_code == 0, result.output
        assert config_file.exists()

        # Reload and assert — the transport choice must have persisted.
        from mneme.config import load_config
        with patch("mneme.config.config_path", return_value=config_file):
            reloaded = load_config()
        assert reloaded.server.transport == "streamable-http"
        assert reloaded.server.host == "127.0.0.1"
        assert reloaded.server.port == 8765
