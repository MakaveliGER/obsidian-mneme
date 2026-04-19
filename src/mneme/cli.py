"""CLI for Mneme — setup, serve, reindex, status, hook-search, install-hooks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from mneme.config import (
    ConfigUpdateError,
    MnemeConfig,
    VaultConfig,
    apply_config_update,
    config_path,
    load_config,
    save_config,
)


@click.group()
@click.version_option(package_name="obsidian-mneme", message="%(prog)s %(version)s")
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

    # Transport
    click.echo("\nMCP transport:")
    click.echo(
        "  stdio            — for Claude Code (CLI hook) and direct stdio "
        "clients.\n"
        "  streamable-http  — long-running server on 127.0.0.1:8765. "
        "Recommended\n"
        "                     for Claudian / Claude Desktop. The Obsidian "
        "plugin can\n"
        "                     auto-start it at Obsidian launch. Vault warm "
        "across\n"
        "                     multiple queries; no per-session cold-start."
    )
    transport = click.prompt(
        "Transport",
        type=click.Choice(["stdio", "streamable-http"]),
        default="streamable-http",
        show_default=True,
    )

    # Create config
    config = MnemeConfig(
        vault=VaultConfig(path=vault_path),
        embedding={"provider": "sentence-transformers", "model": model},
        server={"transport": transport, "host": "127.0.0.1", "port": 8765},
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

    # Progress bar — matters on CPU-only installs where a 200-note first
    # index takes 15-25 min. click.progressbar renders an inline bar with
    # ETA; the callback pattern here lets the Indexer stay UI-agnostic.
    progress_state: dict = {"bar": None}

    def _progress(current: int, total: int, path: str) -> None:
        bar = progress_state["bar"]
        if bar is None:
            bar = click.progressbar(length=total, label="Indexing")
            bar.__enter__()
            progress_state["bar"] = bar
        # click's progressbar wants absolute position via update(n),
        # which is the delta since last update; we pass 1 because we
        # call the callback once per file.
        bar.update(1)

    try:
        result = indexer.index_vault(full=True, progress_callback=_progress)
    finally:
        if progress_state["bar"] is not None:
            progress_state["bar"].__exit__(None, None, None)
        store.close()

    click.echo(f"\nDone! Indexed {result.indexed} notes in {result.duration_seconds:.1f}s")
    click.echo(f"Database: {config.db_path}")
    if transport == "streamable-http":
        click.echo(
            "\nStart the MCP server with:"
            "\n  mneme serve"
            "\n"
            "\nThen point your MCP client at http://127.0.0.1:8765/mcp. "
            "The Obsidian\nplugin (if installed) can also auto-start the "
            "server at Obsidian launch\nvia its 'autoStartServer' setting."
        )
    else:
        click.echo(
            "\nStart the MCP server with:"
            "\n  mneme serve"
            "\n"
            "\nConfigure your MCP client (e.g. Claude Code .claude/mcp.json) "
            "to spawn\n`mneme serve` as a stdio subprocess."
        )


@main.command(name="init")
@click.pass_context
def init(ctx: click.Context) -> None:
    """Alias for `setup` — interactive setup wizard."""
    ctx.invoke(setup)


@main.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default=None,
    help="MCP transport. Overrides config.server.transport. Default: stdio.",
)
@click.option(
    "--host",
    default=None,
    help="HTTP bind address (streamable-http only). Default: 127.0.0.1.",
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="HTTP port (streamable-http only). Default: 8765.",
)
def serve(transport: str | None, host: str | None, port: int | None):
    """Start the MCP server.

    Two transports are supported:

    \b
      stdio            — default. Speaks MCP over stdin/stdout for Claude
                         Desktop, Claudian, and Claude Code.
      streamable-http  — long-running HTTP server. Model is pre-warmed at
                         startup (no first-call latency). Exposes /mcp and
                         /health on 127.0.0.1:8765 by default.
    """
    import logging
    import os
    import sys
    from pathlib import Path

    import platformdirs

    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    # CLI flags override config
    if transport is not None:
        config.server.transport = transport
    if host is not None:
        config.server.host = host
    if port is not None:
        config.server.port = port

    chosen = config.server.transport
    if chosen not in ("stdio", "streamable-http"):
        click.echo(
            f"Error: invalid transport '{chosen}'. "
            "Use 'stdio' or 'streamable-http'.",
            err=True,
        )
        raise SystemExit(1)

    # HTTP-mode safety checks before we open a listening socket.
    if chosen == "streamable-http":
        bind_host = config.server.host
        loopback = {"127.0.0.1", "localhost", "::1", "[::1]"}
        if bind_host not in loopback:
            if os.environ.get("MNEME_ALLOW_NONLOOPBACK") != "1":
                click.echo(
                    f"Error: refusing to bind to '{bind_host}'. Mneme has no "
                    "auth — binding off-loopback exposes your vault to the "
                    "network. Set host to 127.0.0.1, or export "
                    "MNEME_ALLOW_NONLOOPBACK=1 if you know what you're doing.",
                    err=True,
                )
                raise SystemExit(1)
            click.echo(
                f"Warning: binding to '{bind_host}' (non-loopback). No auth. "
                "Any device on this network can read your vault.",
                err=True,
            )
        # Probe the port first so we fail with a clear message instead of a
        # mid-boot uvicorn OSError. 127.0.0.1:port is the canonical case.
        import socket
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((bind_host if bind_host != "localhost" else "127.0.0.1",
                        config.server.port))
        except OSError:
            click.echo(
                f"Error: port {config.server.port} is already in use on "
                f"{bind_host}. Another instance of Mneme, or another app, is "
                "holding the port. Set a different port via "
                f"`mneme serve --port <N>` or edit server.port in config.toml.",
                err=True,
            )
            raise SystemExit(1)
        finally:
            probe.close()

    # stdio MCP transport shares stdout with the JSON-RPC stream — any library
    # that prints model-load progress to stdout would corrupt the protocol.
    # Silence everything progress-related before the model is loaded. Harmless
    # for HTTP mode (stdout is free there).
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TQDM_DISABLE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    # Offline-by-default for cached models. Users who want first-time download
    # or model updates can override with MNEME_ALLOW_NETWORK=1 — avoids a
    # cryptic "offline" error on fresh installs when the HF cache is missing.
    if os.environ.get("MNEME_ALLOW_NETWORK") != "1":
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    log_dir = Path(platformdirs.user_data_dir("mneme"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "mneme-server.log"

    # Debug instrumentation is gated behind MNEME_DEBUG — in production it's
    # noise, during the 11h MCP-hang hunt it was essential. See also the
    # heartbeat + granular [1a/6]..[6/6] logs in embeddings/sentence_transformers.py
    # which read the same env var.
    debug_on = os.environ.get("MNEME_DEBUG") == "1"
    if debug_on:
        import faulthandler
        fault_log = log_dir / "mneme-stacktrace.log"
        _fault_file = open(fault_log, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_fault_file)
        faulthandler.dump_traceback_later(45, repeat=True, file=_fault_file)

    # Rotate the log file — never let it grow unbounded in production.
    from logging.handlers import RotatingFileHandler
    log_level = logging.DEBUG if debug_on else logging.INFO
    # For stdio, stdout is the MCP JSON-RPC channel — logs MUST go to stderr
    # so they don't corrupt the protocol. HTTP mode has stdout free, but we
    # still default to stderr for consistency.
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stderr),
            RotatingFileHandler(
                log_file, maxBytes=10_000_000, backupCount=3, encoding="utf-8"
            ),
        ],
    )
    logging.getLogger(__name__).info("=== mneme serve starting (pid=%d) ===", os.getpid())

    from mneme.server import create_server

    # eager_init=True → HTTP mode pre-warms the model before the server
    # starts listening. Stdio mode ignores this flag (always lazy-on-call).
    server = create_server(config, eager_init=True)
    if chosen == "streamable-http":
        click.echo(
            f"Mneme HTTP server on http://{config.server.host}:{config.server.port}/mcp "
            f"(health: http://{config.server.host}:{config.server.port}/health)",
            err=True,
        )
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")


@main.command()
@click.option("--full", is_flag=True, help="Re-index all notes (ignore hash cache).")
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
def reindex(full: bool, as_json: bool):
    """Re-index the vault (incremental by default)."""
    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.embeddings import get_provider
    from mneme.indexer import Indexer
    from mneme.store import CURRENT_SCHEMA_VERSION, Store

    if not as_json:
        click.echo(f"Indexing vault: {config.vault.path}")
    provider = get_provider(config.embedding)
    # Full reindex is also the migration path: skip the version check so a
    # legacy DB can still be opened, then bump the schema version at the end.
    store = Store(config.db_path, provider.dimension(), skip_version_check=full)
    indexer = Indexer(store, provider, config)

    # Progress bar for interactive runs; JSON mode stays silent so callers
    # parsing stdout don't get partial bytes.
    progress_cb = None
    progress_state: dict = {"bar": None}
    if not as_json:
        def _progress(current: int, total: int, path: str) -> None:
            bar = progress_state["bar"]
            if bar is None:
                bar = click.progressbar(length=total, label="Indexing")
                bar.__enter__()
                progress_state["bar"] = bar
            bar.update(1)
        progress_cb = _progress

    try:
        result = indexer.index_vault(full=full, progress_callback=progress_cb)
    finally:
        if progress_state["bar"] is not None:
            progress_state["bar"].__exit__(None, None, None)
        if full:
            store.set_schema_version(CURRENT_SCHEMA_VERSION)
        store.close()

    if as_json:
        click.echo(json.dumps({
            "indexed": result.indexed,
            "skipped": result.skipped,
            "deleted": result.deleted,
            "duration_seconds": round(result.duration_seconds, 2),
        }))
    else:
        mode = "full" if full else "incremental"
        click.echo(f"\n{mode.capitalize()} reindex complete:")
        click.echo(f"  Indexed: {result.indexed}")
        click.echo(f"  Skipped: {result.skipped}")
        click.echo(f"  Deleted: {result.deleted}")
        click.echo(f"  Duration: {result.duration_seconds:.1f}s")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def status(as_json: bool):
    """Show index statistics."""
    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.store import Store

    # Metadata-only open — skips chunks_vec creation so a fresh DB is never
    # locked to the wrong vector dim.
    store = Store.open_metadata_only(config.db_path)
    stats = store.get_stats(embedding_model=config.embedding.model)
    store.close()

    if as_json:
        click.echo(json.dumps({
            "total_notes": stats.total_notes,
            "total_chunks": stats.total_chunks,
            "last_indexed": stats.last_indexed,
            "embedding_model": stats.embedding_model,
            "db_size_mb": stats.db_size_mb,
        }))
    else:
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


@main.command()
@click.option(
    "--dataset",
    default="tests/golden_dataset.json",
    show_default=True,
    help="Path to golden dataset JSON.",
)
@click.option(
    "--top-k",
    default=10,
    show_default=True,
    help="Number of results to retrieve per question.",
)
def eval(dataset: str, top_k: int):
    """Evaluate retrieval quality against a golden dataset."""
    from pathlib import Path as _Path

    from mneme.eval import load_golden_dataset, evaluate_retrieval, print_report

    dataset_path = _Path(dataset)
    if not dataset_path.exists():
        click.echo(f"Error: Dataset not found: {dataset_path}", err=True)
        raise SystemExit(1)

    try:
        golden = load_golden_dataset(dataset_path)
    except (ValueError, FileNotFoundError) as exc:
        click.echo(f"Error loading dataset: {exc}", err=True)
        raise SystemExit(1)

    click.echo(f"Loaded {len(golden)} questions from {dataset_path}")

    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.embeddings import get_provider
    from mneme.search import SearchEngine
    from mneme.store import Store

    provider = get_provider(config.embedding)
    store = Store(config.db_path, provider.dimension())
    engine = SearchEngine(store=store, embedding_provider=provider, config=config.search)

    click.echo(f"Running evaluation (top_k={top_k})...")
    report = evaluate_retrieval(engine, golden, top_k=top_k)
    store.close()

    print_report(report)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--stale-days", default=30, show_default=True, help="Days after which active notes are stale.")
@click.option("--threshold", default=0.85, show_default=True, help="Similarity threshold for near-duplicates.")
def health(as_json: bool, stale_days: int, threshold: float):
    """Run vault health analysis — orphans, weak links, stale notes, duplicates."""
    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.embeddings import get_provider
    from mneme.gardener import VaultGardener
    from mneme.search import SearchEngine
    from mneme.store import Store

    provider = get_provider(config.embedding)
    store = Store(config.db_path, provider.dimension())
    engine = SearchEngine(store=store, embedding_provider=provider, config=config.search)
    gardener = VaultGardener(store, engine, exclude_patterns=config.health.exclude_patterns)

    if not as_json:
        click.echo("Running vault health analysis...")

    report: dict = {}
    report["orphan_pages"] = gardener.find_orphans()
    report["weakly_linked"] = gardener.find_weakly_linked(top_k=10)
    report["stale_notes"] = gardener.find_stale_notes(days=stale_days)
    report["near_duplicates"] = gardener.find_near_duplicates(threshold=threshold)
    store.close()

    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False))
    else:
        click.echo("\nVault Health Report")
        click.echo("=" * 40)
        click.echo(f"  Orphans:        {len(report['orphan_pages'])}")
        click.echo(f"  Weakly Linked:  {len(report['weakly_linked'])}")
        click.echo(f"  Stale Notes:    {len(report['stale_notes'])}")
        click.echo(f"  Near Duplicates: {len(report['near_duplicates'])}")


@main.command("get-config")
@click.option("--json", "as_json", is_flag=True, default=True, help="Output as JSON (default).")
def get_config(as_json: bool):
    """Show current Mneme configuration."""
    config = load_config()
    data = config.model_dump(exclude_defaults=False)
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False))
    else:
        import tomli_w
        sys.stdout.buffer.write(tomli_w.dumps(data))


@main.command("update-config")
@click.argument("key")
@click.argument("value")
def update_config(key: str, value: str):
    """Update a config setting. Use dot-notation (e.g. embedding.device cuda)."""
    config = load_config()
    try:
        _, old_value, parsed = apply_config_update(config, key, value)
    except ConfigUpdateError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    save_config(config)
    click.echo(f"{key}: {old_value} → {parsed}")


@main.command("search")
@click.argument("query")
@click.option("--top-k", default=10, show_default=True, help="Number of results.")
@click.option("--text", "as_text", is_flag=True, default=False, help="Plain-text output (default is JSON).")
def search(query: str, top_k: int, as_text: bool):
    """Search the vault using hybrid semantic + keyword search."""
    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.embeddings import get_provider
    from mneme.search import SearchEngine, serialize_results
    from mneme.store import Store

    provider = get_provider(config.embedding)
    store = Store(config.db_path, provider.dimension())
    engine = SearchEngine(store=store, embedding_provider=provider, config=config.search)
    results = engine.search(query=query, top_k=top_k)
    store.close()

    # Same serialization the server uses — clean_snippet, relevance_pct,
    # heading-path fallback. CLI and server must not drift on this.
    output = {
        "results": serialize_results(results),
        "query": query,
        "total_results": len(results),
    }

    if as_text:
        click.echo(f"Found {len(results)} results for: {query}")
        for r in results:
            click.echo(f"  [{r.score:.4f}] {r.note_title} ({r.note_path})")
    else:
        click.echo(json.dumps(output, ensure_ascii=False))


@main.command("similar")
@click.argument("path")
@click.option("--top-k", default=5, show_default=True, help="Number of similar notes.")
@click.option("--text", "as_text", is_flag=True, default=False, help="Plain-text output (default is JSON).")
def similar(path: str, top_k: int, as_text: bool):
    """Find semantically similar notes via average chunk embedding."""
    from mneme.paths import normalize_vault_path

    normalized = normalize_vault_path(path)
    if normalized is None:
        click.echo(
            f"Error: Invalid vault path: {path!r}. "
            "Expected a forward-slash vault-relative path (e.g. '02 Projekte/Foo.md').",
            err=True,
        )
        raise SystemExit(1)

    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    from mneme.embeddings import get_provider
    from mneme.search import SearchEngine, serialize_results
    from mneme.store import Store

    provider = get_provider(config.embedding)
    store = Store(config.db_path, provider.dimension())
    engine = SearchEngine(store=store, embedding_provider=provider, config=config.search)
    results = engine.get_similar(normalized, top_k=top_k)
    store.close()

    output = {
        "results": serialize_results(results),
        "source_path": normalized,
        "total_results": len(results),
    }

    if as_text:
        click.echo(f"Found {len(results)} similar notes for: {normalized}")
        for r in results:
            click.echo(f"  [{r.score:.4f}] {r.note_title} ({r.note_path})")
    else:
        click.echo(json.dumps(output, ensure_ascii=False))


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
    source_path = _extract_source_path(hook_data)

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
        from mneme.store import Store

        # Metadata-only open — BM25 does not touch chunks_vec, and skipping
        # that table avoids baking a dummy dim into a fresh DB.
        store = Store.open_metadata_only(config.db_path)
        # Fetch extra candidates so we still have enough after self-filter
        results = store.bm25_search(query, top_k=4 if source_path else 3)
        store.close()
    except Exception:
        _emit_context(None)
        return

    # Filter the note Claude is about to read — otherwise the hook returns
    # the file itself as top result (noise, not signal).
    if source_path:
        results = [r for r in results if r.note_path != source_path][:3]

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


def _extract_source_path(hook_data: dict) -> str | None:
    """Return the vault-relative path of the note Claude is about to read.

    Used to exclude the source file from hook-search results (otherwise the
    hook injects the file Claude is already opening — noise, not signal).
    Returns None for non-Read tools.
    """
    tool_input = hook_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None
    try:
        config = load_config()
        vault_root = Path(config.vault.path).resolve()
        abs_path = Path(file_path).resolve()
        rel = abs_path.relative_to(vault_root)
        return str(rel).replace("\\", "/")
    except Exception:
        return None


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
@click.option(
    "--force",
    is_flag=True,
    help="Skip the safety check when --vault-path differs from the configured vault.",
)
def install_hooks(vault_path: str | None, settings_file: str, force: bool):
    """Install Mneme PreToolUse hook into .claude/settings[.local].json.

    Reads the existing settings file (if any), merges the Mneme hook
    configuration, shows the diff, and asks for confirmation before writing.
    """
    from mneme.hooks import generate_hook_config

    # Resolve configured vault (source of truth for the safety check below)
    try:
        cfg = load_config()
        configured_vault = Path(cfg.vault.path).resolve() if cfg.vault.path else None
    except Exception:
        configured_vault = None

    # Resolve requested vault path
    if vault_path:
        resolved_vault = Path(vault_path).resolve()
    else:
        resolved_vault = configured_vault

    if not resolved_vault or not resolved_vault.exists():
        click.echo(
            "Error: Could not determine vault path. "
            "Pass --vault-path or run 'mneme setup' first.",
            err=True,
        )
        raise SystemExit(1)

    # Safety check: refuse to install hooks into a directory that isn't the
    # configured Mneme vault unless the user explicitly passes --force.
    # Prevents accidentally installing `mneme hook-search` as a PreToolUse hook
    # in unrelated repos.
    if configured_vault and resolved_vault != configured_vault and not force:
        click.echo(
            f"Error: --vault-path ({resolved_vault}) does not match the configured "
            f"Mneme vault ({configured_vault}).\n"
            "Pass --force if you really want to install the hook outside the "
            "configured vault.",
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


@main.command("auto-search")
@click.argument("mode", type=click.Choice(["off", "smart", "always"]))
def auto_search(mode: str):
    """Configure automatic search behavior.

    \b
    Modes:
      off     — Only explicit @mneme / search_notes calls
      smart   — CLAUDE.md rule: Claude uses search_notes proactively
      always  — Smart + PreToolUse hooks for automatic context injection
    """
    from mneme.auto_search import apply_mode

    config = load_config()
    if not config.vault.path:
        click.echo("Error: No vault path configured. Run 'mneme setup' first.", err=True)
        raise SystemExit(1)

    vault_path = Path(config.vault.path).resolve()
    result = apply_mode(mode, vault_path, config.auto_search)

    # Persist new mode
    config.auto_search.mode = mode
    save_config(config)

    # Feedback
    click.echo(f"Auto-search mode set to: {mode}")
    if result["claude_md_changed"]:
        claude_md = vault_path / config.auto_search.claude_md_path
        click.echo(f"  CLAUDE.md updated: {claude_md}")
    else:
        click.echo("  CLAUDE.md: no change")
    if result["hooks_changed"]:
        settings_path = vault_path / ".claude" / "settings.local.json"
        click.echo(f"  Hooks updated: {settings_path}")
    else:
        click.echo("  Hooks: no change")


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


def cli_entry() -> None:
    """Entry point with user-friendly error handling.

    Click handles its own errors (Abort, ClickException). This wrapper
    catches Python exceptions and shows a concise message. Set MNEME_DEBUG=1
    for the full traceback.
    """
    try:
        main()
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)
    except (FileNotFoundError, PermissionError, OSError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        if os.environ.get("MNEME_DEBUG"):
            raise
        click.echo(f"Error: {type(e).__name__}: {e}", err=True)
        click.echo("Run with MNEME_DEBUG=1 for full traceback.", err=True)
        sys.exit(1)
