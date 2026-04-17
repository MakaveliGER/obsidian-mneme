"""Vault-path utilities shared by the CLI and the MCP server.

Lives outside `server.py` so callers (CLI commands like `mneme similar`)
don't have to import the entire MCP stack just for path validation.
"""

from __future__ import annotations


def normalize_vault_path(path: str) -> str | None:
    """Validate and normalize a vault-relative path from untrusted input.

    Rejects absolute paths and parent-directory traversal. Normalizes
    backslashes to forward slashes so lookups match the stored form.
    Returns None if the path is invalid.
    """
    if not isinstance(path, str) or not path.strip():
        return None
    cleaned = path.strip().replace("\\", "/")
    # Reject absolute paths (Unix `/foo`, Windows `C:/foo`) and traversal.
    if cleaned.startswith("/") or (len(cleaned) > 1 and cleaned[1] == ":"):
        return None
    if ".." in cleaned.split("/"):
        return None
    return cleaned
