"""Claude Code hook integration for automatic Vault context injection."""

from __future__ import annotations


def generate_hook_config() -> dict:
    """Generate Claude Code hook config for automatic context injection.

    The hook fires on PreToolUse for Read tool calls. Before Claude reads a
    file, Mneme performs a fast BM25 search against the Vault index and injects
    the top-3 relevant notes as ``additionalContext``.

    Returns:
        dict ready to be merged into `.claude/settings.json` (or
        `settings.local.json`).
    """
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "mneme hook-search",
                            "timeout": 5,
                        }
                    ],
                }
            ]
        }
    }
