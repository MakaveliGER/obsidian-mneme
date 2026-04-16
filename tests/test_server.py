"""Tests for mneme.server — MCP server tool definitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mneme.server import create_server


def test_server_has_six_tools():
    """The MCP server must expose exactly 6 tools."""
    with patch("mneme.server.load_config") as mock_config:
        mock_config.return_value = MagicMock()
        mock_config.return_value.vault.path = ""
        server = create_server(mock_config.return_value)

    # FastMCP stores tools internally — check via list_tools
    tool_names = list(server._tool_manager._tools.keys())
    assert len(tool_names) == 6
    expected = {"search_notes", "get_similar", "vault_stats", "reindex", "get_config", "update_config"}
    assert set(tool_names) == expected
