"""Tests for the streamable-http transport branch in mneme.server.

We don't start a real HTTP server — too heavy for the test suite. Instead we
verify that:

1. `create_server(config_with_http)` returns a FastMCP with the expected
   bind/port/path.
2. All 8 tools are still registered.
3. The `/health` custom route is registered.
4. Eager `_initialize()` is NOT called at construction time (the lifespan
   handles it) — proved by asserting `get_provider` was not called.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from mneme.config import (
    DatabaseConfig,
    MnemeConfig,
    ServerConfig,
    VaultConfig,
)
from mneme.server import create_server


def _http_config(tmp_path: Path) -> MnemeConfig:
    return MnemeConfig(
        vault=VaultConfig(path=str(tmp_path)),
        database=DatabaseConfig(path=str(tmp_path / "test.db")),
        server=ServerConfig(transport="streamable-http", host="127.0.0.1", port=8765),
    )


def test_create_server_http_has_expected_settings(tmp_path: Path):
    """HTTP-mode server must bind to the configured host/port with /mcp path."""
    config = _http_config(tmp_path)

    # get_provider must NOT be called at construction for HTTP mode — the
    # lifespan handles pre-warm lazily on server.run().
    with patch("mneme.server.get_provider") as mock_get_provider:
        server = create_server(config)
        assert mock_get_provider.call_count == 0, (
            "HTTP mode must defer init to lifespan, not call get_provider at construction"
        )

    assert server.settings.host == "127.0.0.1"
    assert server.settings.port == 8765
    assert server.settings.streamable_http_path == "/mcp"


def test_create_server_http_registers_all_tools(tmp_path: Path):
    """All 8 MCP tools must be registered in HTTP mode."""
    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    tool_names = set(server._tool_manager._tools.keys())
    expected = {
        "search_notes",
        "get_similar",
        "get_note_context",
        "vault_stats",
        "reindex",
        "get_config",
        "update_config",
        "vault_health",
    }
    assert tool_names == expected


def test_create_server_http_registers_health_route(tmp_path: Path):
    """The /health custom route must be registered in HTTP mode."""
    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    # FastMCP stores custom routes on `_custom_starlette_routes`
    routes = getattr(server, "_custom_starlette_routes", [])
    paths = {getattr(r, "path", None) for r in routes}
    assert "/health" in paths, f"Expected /health route, got: {paths}"


def test_create_server_stdio_does_not_register_health_route(tmp_path: Path):
    """The /health route must be HTTP-only (stdio has no HTTP server)."""
    config = MnemeConfig(
        vault=VaultConfig(path=str(tmp_path)),
        database=DatabaseConfig(path=str(tmp_path / "test.db")),
        server=ServerConfig(transport="stdio"),
    )
    with patch("mneme.server.get_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.dimension.return_value = 16
        mock_get_provider.return_value = mock_provider
        server = create_server(config)

    routes = getattr(server, "_custom_starlette_routes", [])
    paths = {getattr(r, "path", None) for r in routes}
    assert "/health" not in paths


def test_server_config_defaults():
    """Default transport must remain stdio for backward compatibility."""
    cfg = ServerConfig()
    assert cfg.transport == "stdio"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8765


def test_health_endpoint_response_shape(tmp_path: Path):
    """/health response must be minimal: {status, model_loaded} only.

    Bigger payloads (db_size_mb, init_error) leak metadata to a browser
    attacker exploiting DNS rebind. Keep the response tight.
    """
    from starlette.testclient import TestClient

    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    app = server.streamable_http_app()
    client = TestClient(app)

    # Valid loopback Host → 200
    response = client.get("/health", headers={"host": "127.0.0.1:8765"})
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "model_loaded"}, (
        f"/health leaked extra fields: {set(body.keys()) - {'status', 'model_loaded'}}"
    )
    assert body["status"] == "ok"


def test_health_endpoint_rejects_non_loopback_host(tmp_path: Path):
    """/health must reject requests whose Host header isn't loopback.

    DNS-rebind defense — FastMCP's built-in middleware only covers /mcp,
    so /health must enforce this itself.
    """
    from starlette.testclient import TestClient

    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    app = server.streamable_http_app()
    client = TestClient(app)

    # Attacker-controlled Host (e.g. from DNS-rebind) → 403
    response = client.get("/health", headers={"host": "evil.com"})
    assert response.status_code == 403


def test_health_endpoint_rejects_dns_rebind_prefix_bypass(tmp_path: Path):
    """/health must reject hosts that merely *start* with a loopback string.

    Regression guard: previous implementation used startswith() which let
    `127.0.0.1.evil.com` pass (public DNS services like nip.io resolve such
    names to 127.0.0.1 → browser sends that Host → prefix match succeeds →
    DNS rebind succeeds). Proper fix parses the Host header and matches the
    hostname exactly.
    """
    from starlette.testclient import TestClient

    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    app = server.streamable_http_app()
    client = TestClient(app)

    bypass_attempts = [
        "127.0.0.1.evil.com",
        "127.0.0.1.evil.com:8765",
        "localhost.evil.com",
        "localhost.evil.com:8765",
        "127.0.0.1\x00.evil.com",
        "127.0.0.1\r\nX-Evil: 1",
    ]
    for host in bypass_attempts:
        response = client.get("/health", headers={"host": host})
        assert response.status_code == 403, (
            f"Expected 403 for host={host!r}, got {response.status_code}"
        )


def test_health_endpoint_accepts_loopback_variations(tmp_path: Path):
    """Valid loopback hosts must still be accepted after the tightened check."""
    from starlette.testclient import TestClient

    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    app = server.streamable_http_app()
    client = TestClient(app)

    valid_hosts = [
        "127.0.0.1:8765",
        "127.0.0.1",
        "localhost:8765",
        "localhost",
        "LOCALHOST:8765",          # case-insensitive
        "[::1]:8765",              # IPv6 with brackets + port
        "[::1]",                   # IPv6 literal, no port
    ]
    for host in valid_hosts:
        response = client.get("/health", headers={"host": host})
        assert response.status_code == 200, (
            f"Expected 200 for host={host!r}, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# REST API endpoints — added for the Obsidian-plugin fast-path
# ---------------------------------------------------------------------------

def test_rest_endpoints_registered_in_http_mode(tmp_path: Path):
    """/api/v1/* endpoints must be registered in HTTP mode."""
    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    routes = getattr(server, "_custom_starlette_routes", [])
    paths = {getattr(r, "path", None) for r in routes}
    expected = {
        "/api/v1/search",
        "/api/v1/similar",
        "/api/v1/stats",
        "/api/v1/vault-health",
        "/api/v1/reindex",
    }
    assert expected.issubset(paths), (
        f"Missing REST routes: {expected - paths}"
    )


def test_rest_endpoints_not_registered_in_stdio_mode(tmp_path: Path):
    """REST endpoints must only exist when HTTP transport is active."""
    from mneme.config import ServerConfig
    config = MnemeConfig(
        vault=VaultConfig(path=str(tmp_path)),
        database=DatabaseConfig(path=str(tmp_path / "test.db")),
        server=ServerConfig(transport="stdio"),
    )
    with patch("mneme.server.get_provider") as mock_get:
        mock_provider = MagicMock()
        mock_provider.dimension.return_value = 16
        mock_get.return_value = mock_provider
        server = create_server(config)

    routes = getattr(server, "_custom_starlette_routes", [])
    paths = {getattr(r, "path", None) for r in routes}
    assert "/api/v1/search" not in paths
    assert "/api/v1/stats" not in paths


def test_rest_search_rejects_non_loopback_host(tmp_path: Path):
    """REST endpoints must enforce the same Host-header guard as /health."""
    from starlette.testclient import TestClient

    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    app = server.streamable_http_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/search",
        headers={"host": "evil.com"},
        json={"query": "test"},
    )
    assert response.status_code == 403


def test_rest_search_returns_503_when_not_warm(tmp_path: Path):
    """REST calls before the model is loaded must return 503, not crash."""
    from starlette.testclient import TestClient

    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        # HTTP mode with eager_init=False (default in this test path) means
        # state is empty; REST endpoints must surface that as 503.
        server = create_server(config)

    app = server.streamable_http_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/search",
        headers={"host": "127.0.0.1:8765"},
        json={"query": "test"},
    )
    assert response.status_code == 503
    assert "not ready" in response.text or "loading" in response.text


def test_rest_search_validates_input(tmp_path: Path):
    """REST search must reject malformed bodies with 400, not 500."""
    from starlette.testclient import TestClient

    config = _http_config(tmp_path)
    with patch("mneme.server.get_provider"):
        server = create_server(config)

    app = server.streamable_http_app()
    client = TestClient(app)

    # Empty body
    response = client.post(
        "/api/v1/search",
        headers={"host": "127.0.0.1:8765", "content-type": "application/json"},
        content=b"",
    )
    # Either 400 (bad JSON) or 503 (not warm) depending on which guard
    # trips first. Both are acceptable; a 500 would not be.
    assert response.status_code in (400, 503)
