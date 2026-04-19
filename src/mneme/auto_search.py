"""Auto-search mode management: CLAUDE.md injection and hook installation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from mneme.config import AutoSearchConfig

CLAUDE_MD_MARKER_START = "<!-- mneme:auto-search:start -->"
CLAUDE_MD_MARKER_END = "<!-- mneme:auto-search:end -->"

CLAUDE_MD_BLOCK = """<!-- mneme:auto-search:start -->
## Mneme — Semantische Vault-Suche
Bei Wissensfragen, Recherchen oder wenn der Kontext unklar ist: Nutze `search_notes` proaktiv, bevor du antwortest. Das Tool findet semantisch verwandte Notizen, nicht nur exakte String-Matches.
<!-- mneme:auto-search:end -->"""


def inject_claude_md(vault_path: Path, claude_md_path: str = "CLAUDE.md") -> bool:
    """Inject the Mneme auto-search block into CLAUDE.md.

    - If the file doesn't exist: create it with the block.
    - If the file exists and block is already present: no-op (idempotent).
    - If the file exists but block is absent: append block at the end.

    Returns:
        True if the file was changed, False otherwise.
    """
    target = vault_path / claude_md_path

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(CLAUDE_MD_BLOCK + "\n", encoding="utf-8")
        return True

    content = target.read_text(encoding="utf-8")

    # Idempotency check: block already present?
    if CLAUDE_MD_MARKER_START in content and CLAUDE_MD_MARKER_END in content:
        return False

    # Append block
    separator = "\n\n" if not content.endswith("\n\n") else ""
    if content.endswith("\n") and not content.endswith("\n\n"):
        separator = "\n"
    elif not content.endswith("\n"):
        separator = "\n\n"

    new_content = content + separator + CLAUDE_MD_BLOCK + "\n"
    target.write_text(new_content, encoding="utf-8")
    return True


def remove_claude_md(vault_path: Path, claude_md_path: str = "CLAUDE.md") -> bool:
    """Remove the Mneme auto-search block from CLAUDE.md.

    Removes the block between markers (inclusive) and cleans up surrounding
    blank lines.

    Returns:
        True if the file was changed, False otherwise.
    """
    target = vault_path / claude_md_path

    if not target.exists():
        return False

    content = target.read_text(encoding="utf-8")

    if CLAUDE_MD_MARKER_START not in content:
        return False

    # Remove block including markers — also strip surrounding blank lines
    pattern = r"\n*" + re.escape(CLAUDE_MD_MARKER_START) + r".*?" + re.escape(CLAUDE_MD_MARKER_END) + r"\n?"
    new_content = re.sub(pattern, "", content, flags=re.DOTALL)

    # Normalise: no more than two consecutive newlines at the end
    new_content = re.sub(r"\n{3,}$", "\n", new_content)

    if new_content == content:
        return False

    target.write_text(new_content, encoding="utf-8")
    return True


def install_hooks(vault_path: Path, matchers: list[str]) -> bool:
    """Reconcile Mneme PreToolUse hooks with the requested matcher list.

    The previous implementation deduplicated on command string alone, which
    means the very first ``install_hooks(['Read'])`` call locked the set: a
    later ``install_hooks(['Read','Bash'])`` kept seeing the same command and
    never appended the ``Bash`` entry. This function now removes any
    existing Mneme-owned entries first and re-installs exactly the entries
    generated for *matchers*, so the file always reflects the requested set.
    Non-Mneme hooks from the user or other tools are preserved.

    Returns:
        True if the file content changed, False otherwise.
    """
    from mneme.hooks import generate_hook_config

    settings_dir = vault_path / ".claude"
    settings_path = settings_dir / "settings.local.json"

    existing: dict = {}
    if settings_path.exists():
        try:
            with open(settings_path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    def _is_mneme_entry(entry: dict) -> bool:
        inner_hooks = entry.get("hooks", [entry])
        return any(
            "mneme hook-search" in h.get("command", "")
            for h in inner_hooks
        )

    hook_config = generate_hook_config(matchers)
    before_hooks: dict = dict(existing.get("hooks", {}))

    # Start from existing hooks minus any Mneme-owned entries.
    base_hooks: dict = {}
    for event_name, entries in before_hooks.items():
        base_hooks[event_name] = [
            entry for entry in entries if not _is_mneme_entry(entry)
        ]

    # Append the requested Mneme entries exactly once per matcher.
    for event_name, new_entries in hook_config["hooks"].items():
        base_hooks.setdefault(event_name, []).extend(new_entries)

    # Drop event keys we emptied out to avoid noisy diffs.
    base_hooks = {k: v for k, v in base_hooks.items() if v}

    if base_hooks == before_hooks:
        return False

    merged = dict(existing)
    merged["hooks"] = base_hooks

    settings_dir.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return True


def remove_hooks(vault_path: Path) -> bool:
    """Remove all Mneme hooks from .claude/settings.local.json.

    Identifies Mneme hooks by command strings containing "mneme hook-search".

    Returns:
        True if the file was changed, False otherwise.
    """
    settings_path = vault_path / ".claude" / "settings.local.json"

    if not settings_path.exists():
        return False

    try:
        with open(settings_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False

    hooks_section: dict = data.get("hooks", {})
    changed = False

    new_hooks: dict = {}
    for event_name, entries in hooks_section.items():
        filtered = []
        for entry in entries:
            inner_hooks = entry.get("hooks", [entry])
            is_mneme = any(
                "mneme hook-search" in h.get("command", "")
                for h in inner_hooks
            )
            if is_mneme:
                changed = True
            else:
                filtered.append(entry)
        new_hooks[event_name] = filtered

    if not changed:
        return False

    data["hooks"] = new_hooks
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return True


def apply_mode(mode: str, vault_path: Path, config: AutoSearchConfig) -> dict:
    """Apply the given auto-search mode.

    Modes:
        off:    Remove CLAUDE.md block and all Mneme hooks.
        smart:  Inject CLAUDE.md block, remove hooks.
        always: Inject CLAUDE.md block and install hooks.

    Returns:
        dict with keys: mode, claude_md_changed, hooks_changed
    """
    if mode == "off":
        claude_md_changed = remove_claude_md(vault_path, config.claude_md_path)
        hooks_changed = remove_hooks(vault_path)
    elif mode == "smart":
        claude_md_changed = inject_claude_md(vault_path, config.claude_md_path)
        hooks_changed = remove_hooks(vault_path)
    elif mode == "always":
        claude_md_changed = inject_claude_md(vault_path, config.claude_md_path)
        hooks_changed = install_hooks(vault_path, config.hook_matchers)
    else:
        raise ValueError(f"Unknown auto-search mode: {mode!r}")

    return {
        "mode": mode,
        "claude_md_changed": claude_md_changed,
        "hooks_changed": hooks_changed,
    }
