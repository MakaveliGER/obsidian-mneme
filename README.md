<p align="center">
  <img src="design/banner.png" alt="Mneme Banner" width="100%">
</p>

# Mneme

Local MCP server for semantic Obsidian vault search. Headless RAG — Mneme indexes and searches your vault, Claude does the reasoning.

## Features

- **Hybrid Search** — Vector (BGE-M3) + BM25 keyword search with Reciprocal Rank Fusion
- **6 MCP Tools** — search_notes, get_similar, vault_stats, reindex, get_config, update_config
- **Heading-aware Chunking** — Semantic context injection (title, folder, tags per chunk)
- **File Watcher** — Automatic re-indexing on vault changes
- **Zero Cloud** — Everything runs locally, no API keys needed

## Quick Start

```bash
# Install
pip install mneme

# Setup (interactive wizard)
mneme setup

# Or with uvx (no install needed)
uvx mneme setup
```

## Usage with Claudian

Add to your vault's `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "mneme": {
      "command": "uvx",
      "args": ["mneme", "serve"]
    }
  }
}
```

Then in Claudian: `@mneme search_notes "your query"`

## CLI Commands

| Command | Description |
|---|---|
| `mneme setup` | Interactive setup wizard |
| `mneme serve` | Start MCP server (stdio) |
| `mneme reindex` | Re-index vault (incremental) |
| `mneme reindex --full` | Full re-index |
| `mneme status` | Show index statistics |

## Tech Stack

- **Embeddings**: BGE-M3 via sentence-transformers (1024 dim, multilingual)
- **Vector Store**: SQLite + sqlite-vec
- **Keyword Search**: SQLite FTS5 (BM25)
- **Fusion**: Reciprocal Rank Fusion (RRF)
- **MCP**: FastMCP (stdio transport)
- **Config**: TOML + Pydantic Settings

## License

MIT
