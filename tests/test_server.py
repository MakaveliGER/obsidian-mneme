"""Tests for mneme.server — MCP server tool definitions."""

from __future__ import annotations

import math
import random
from pathlib import Path
from unittest.mock import MagicMock, patch

from mneme.config import MnemeConfig, VaultConfig, EmbeddingConfig, DatabaseConfig
from mneme.server import create_server


def test_server_has_seven_tools(tmp_path: Path):
    """The MCP server must expose exactly 7 tools."""
    db_path = tmp_path / "test.db"
    config = MnemeConfig(
        vault=VaultConfig(path=str(tmp_path)),
        database=DatabaseConfig(path=str(db_path)),
    )

    with patch("mneme.server.get_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.dimension.return_value = 16
        mock_get_provider.return_value = mock_provider
        server = create_server(config)

    tool_names = list(server._tool_manager._tools.keys())
    assert len(tool_names) == 7
    expected = {"search_notes", "get_similar", "get_note_context", "vault_stats", "reindex", "get_config", "update_config"}
    assert set(tool_names) == expected
