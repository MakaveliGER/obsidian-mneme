"""Claude Code hook integration for automatic Vault context injection."""

from __future__ import annotations


def generate_hook_config(matchers: list[str] | None = None) -> dict:
    """Generate Claude Code hook config for automatic context injection.

    The hook fires on PreToolUse for the specified tool matchers. Before Claude
    runs those tools, Mneme performs a fast BM25 search against the Vault index
    and injects the top-3 relevant notes as ``additionalContext``.

    Args:
        matchers: List of tool matchers (e.g. ["Read", "Bash"]). Defaults to
            ["Read"] if not provided.

    Returns:
        dict ready to be merged into `.claude/settings.json` (or
        `settings.local.json`).
    """
    if matchers is None:
        matchers = ["Read"]

    entries = [
        {
            "matcher": matcher,
            "hooks": [
                {
                    "type": "command",
                    "command": "mneme hook-search",
                    "timeout": 5,
                }
            ],
        }
        for matcher in matchers
    ]

    return {
        "hooks": {
            "PreToolUse": entries,
        }
    }
