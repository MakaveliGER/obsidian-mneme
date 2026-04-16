"""CLI for Mneme — setup, serve, reindex, status, hook-search, install-hooks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from mneme.config import (
    MnemeConfig,
    VaultConfig,
    config_path,
    load_config,
    save_config,
)


@click.group()
def main():
    """Mneme — Local MCP server for semantic Obsidian vault search."""
    pass


@main.command()
def setup():
    """Interactive setup wizard — creates config and builds initial index."""
    click.echo("Mneme Setup")
    click.echo("=" * 40)

    # Vault path
    vault_path = click.prompt("Vault path", type=str)
    vault_path = str(Path(vault_path).resolve())

    # Embedding model
    model = click.prompt(
        "Embedding model",
        default="BAAI/bge-m3",
        show_default=True,
    )

    # Create config
    config = MnemeConfig(
        vault=VaultConfig(path=vault_path),
        embedding={"provider": "sentence-transformers", "model": model},
    )
    saved_path = save_config(config)
    click.echo(f"\nConfig saved to: {saved_path}")

    # Initial index
    click.echo(f"\nIndexing vault: {vault_path}")
    click.echo("This may take a while on first run (downloading embedding model)...")

    from mneme.embeddings import get_provider
    from mneme.indexer import Indexer
    from mneme.store import Store

    provider = get_provider(config.embedding)
    store = Store(config.db_path, provider.dimension())
    indexer = Indexer(store, provider, config)
    result = indexer.index_vault(full=True)
    store.close()

    click.echo(f"\nDone! Indexed {result.indexed} notes in {result.duration_seconds:.1f}s")
    click.echo(f"Database: {config.db_path}")
    click.echo(f"\nStart the MCP server with: mneme serve")


@main.command()
def serve():
    """Start the MCP server (stdio transport for Claudian)."""
    import logging
    import sys

    # Log to stderr so it doesn't interfere with stdio MCP transport
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.server import create_server

    server = create_server(config)
    server.run(transport="stdio")


@main.command()
@click.option("--full", is_flag=True, help="Re-index all notes (ignore hash cache).")
def reindex(full: bool):
    """Re-index the vault (incremental by default)."""
    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.embeddings import get_provider
    from mneme.indexer import Indexer
    from mneme.store import Store

    click.echo(f"Indexing vault: {config.vault.path}")
    provider = get_provider(config.embedding)
    store = Store(config.db_path, provider.dimension())
    indexer = Indexer(store, provider, config)
    result = indexer.index_vault(full=full)
    store.close()

    mode = "full" if full else "incremental"
    click.echo(f"\n{mode.capitalize()} reindex complete:")
    click.echo(f"  Indexed: {result.indexed}")
    click.echo(f"  Skipped: {result.skipped}")
    click.echo(f"  Deleted: {result.deleted}")
    click.echo(f"  Duration: {result.duration_seconds:.1f}s")


@main.command()
def status():
    """Show index statistics."""
    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.embeddings import get_provider
    from mneme.store import Store

    provider = get_provider(config.embedding)
    store = Store(config.db_path, provider.dimension())
    stats = store.get_stats(embedding_model=config.embedding.model)
    store.close()

    click.echo("Mneme Index Status")
    click.echo("=" * 40)
    click.echo(f"  Vault:     {config.vault.path}")
    click.echo(f"  Notes:     {stats.total_notes}")
    click.echo(f"  Chunks:    {stats.total_chunks}")
    click.echo(f"  Model:     {stats.embedding_model}")
    click.echo(f"  DB Size:   {stats.db_size_mb} MB")
    click.echo(f"  Last Index: {stats.last_indexed or 'never'}")
    click.echo(f"  Config:    {config_path()}")
    click.echo(f"  Database:  {config.db_path}")


@main.command("hook-search")
def hook_search():
    """BM25 hook search for Claude Code PreToolUse context injection.

    Reads Claude Code hook JSON from stdin, extracts a query, runs a fast
    BM25-only search (no embedding model load), and outputs the top-3 results
    as ``additionalContext`` JSON for Claude Code to inject into context.

    Exit 0 always — on any error we return empty context so Claude proceeds.
    """
    # Read stdin (Claude Code sends hook JSON here)
    try:
        raw = sys.stdin.read()
        hook_data = json.loads(raw) if raw.strip() else {}
    except Exception:
        hook_data = {}

    # Extract query from tool_input — for Read tool this is the file_path,
    # but we use it as a search seed (basename is often meaningful).
    query = _extract_query(hook_data)

    if not query:
        # No query → emit empty context, let Claude proceed
        _emit_context(None)
        return

    # Load config — if anything fails, proceed silently
    try:
        config = load_config()
        if not config.vault.path:
            _emit_context(None)
            return
    except Exception:
        _emit_context(None)
        return

    # BM25-only search (no embedding model load — fast path)
    try:
        import sqlite3
        from mneme.store import Store

        # Open store with a dummy embedding dim (we only use BM25)
        # Use dim=1 to avoid loading anything; Store._load_extensions is needed
        # for sqlite-vec but the BM25 path doesn't touch chunks_vec.
        store = Store(config.db_path, embedding_dim=1)
        results = store.bm25_search(query, top_k=3)
        store.close()
    except Exception:
        _emit_context(None)
        return

    if not results:
        _emit_context(None)
        return

    # Format compact output
    lines = [f"[Mneme Context] Found {len(results)} relevant note(s):"]
    for i, r in enumerate(results, start=1):
        # One-line snippet: first 80 chars of content, stripped
        snippet = r.content.replace("\n", " ").strip()[:80]
        lines.append(f'{i}. "{r.note_title}" ({r.note_path}) — {snippet}')

    context_text = "\n".join(lines)
    _emit_context(context_text)


def _extract_query(hook_data: dict) -> str:
    """Extract a meaningful query string from Claude Code hook JSON.

    Priority:
    1. tool_input.file_path  — for Read tool (basename without extension)
    2. tool_input.command    — for Bash tool (first 100 chars)
    3. tool_input.query      — for search tools
    4. Empty string if nothing found.
    """
    tool_input = hook_data.get("tool_input", {})

    # Read tool → file_path
    file_path = tool_input.get("file_path", "")
    if file_path:
        # Use the filename stem as the query; it's usually the most meaningful
        # word (e.g. "KI-Strategie" from "02 Projekte/KI-Strategie.md")
        stem = Path(file_path).stem
        return stem if stem else file_path

    # Bash tool → command
    command = tool_input.get("command", "")
    if command:
        return command[:100]

    # Generic query field
    query = tool_input.get("query", "")
    if query:
        return str(query)[:200]

    return ""


def _emit_context(context: str | None) -> None:
    """Write Claude Code PreToolUse additionalContext JSON to stdout and exit 0."""
    if not context:
        # No context — output empty JSON, Claude proceeds normally
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
    else:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": context,
            }
        }
    sys.stdout.write(json.dumps(output))
    sys.stdout.flush()
    sys.exit(0)


@main.command("install-hooks")
@click.option(
    "--vault-path",
    default=None,
    help="Path to the Obsidian vault (defaults to configured vault path).",
)
@click.option(
    "--settings-file",
    type=click.Choice(["settings.json", "settings.local.json"]),
    default="settings.local.json",
    show_default=True,
    help="Which Claude Code settings file to update.",
)
def install_hooks(vault_path: str | None, settings_file: str):
    """Install Mneme PreToolUse hook into .claude/settings[.local].json.

    Reads the existing settings file (if any), merges the Mneme hook
    configuration, shows the diff, and asks for confirmation before writing.
    """
    from mneme.hooks import generate_hook_config

    # Resolve vault path
    if vault_path:
        resolved_vault = Path(vault_path).resolve()
    else:
        try:
            config = load_config()
            resolved_vault = Path(config.vault.path).resolve() if config.vault.path else None
        except Exception:
            resolved_vault = None

    if not resolved_vault or not resolved_vault.exists():
        click.echo(
            "Error: Could not determine vault path. "
            "Pass --vault-path or run 'mneme setup' first.",
            err=True,
        )
        raise SystemExit(1)

    settings_dir = resolved_vault / ".claude"
    settings_path = settings_dir / settings_file

    # Load existing settings
    existing: dict = {}
    if settings_path.exists():
        try:
            with open(settings_path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception as e:
            click.echo(f"Warning: Could not read {settings_path}: {e}", err=True)

    # Build merged config
    hook_config = generate_hook_config()
    merged = _deep_merge_hooks(existing, hook_config)

    # Show what will change
    click.echo(f"\nTarget file: {settings_path}")
    click.echo("\nCurrent hooks section:")
    click.echo(json.dumps(existing.get("hooks", {}), indent=2, ensure_ascii=False))
    click.echo("\nNew hooks section (after merge):")
    click.echo(json.dumps(merged.get("hooks", {}), indent=2, ensure_ascii=False))

    # Confirm
    if not click.confirm("\nWrite changes?"):
        click.echo("Aborted.")
        raise SystemExit(0)

    # Write
    settings_dir.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")

    click.echo(f"\nDone. Hook installed in: {settings_path}")
    click.echo("Restart Claude Code (Claudian) for the hook to take effect.")


def _deep_merge_hooks(base: dict, override: dict) -> dict:
    """Merge hook config dicts. Mneme hook entries are added if not already present.

    For the ``hooks`` key: each event list is merged by appending new entries
    that don't already have an identical ``command``.
    """
    result = dict(base)

    for key, value in override.items():
        if key != "hooks":
            result[key] = value
            continue

        # Merge hooks section
        base_hooks: dict = dict(result.get("hooks", {}))
        for event_name, new_entries in value.items():
            existing_entries: list = list(base_hooks.get(event_name, []))
            # Collect existing commands to avoid duplicates
            existing_commands = {
                h.get("command", "")
                for entry in existing_entries
                for h in entry.get("hooks", [entry])  # support both formats
            }
            for entry in new_entries:
                # Check if any hook command in this entry already exists
                entry_commands = {
                    h.get("command", "")
                    for h in entry.get("hooks", [entry])
                }
                if not entry_commands.intersection(existing_commands):
                    existing_entries.append(entry)
            base_hooks[event_name] = existing_entries

        result["hooks"] = base_hooks

    return result
