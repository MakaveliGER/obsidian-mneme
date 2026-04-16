"""CLI for Mneme — setup, serve, reindex, status."""

from __future__ import annotations

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
