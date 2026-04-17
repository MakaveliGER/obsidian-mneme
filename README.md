<p align="center">
  <img src="design/banner.png" alt="Mneme Banner" width="100%">
</p>

# Mneme

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

**Headless RAG / Retrieval Sidecar for Obsidian.** Mneme indexiert und durchsucht deinen Vault — Claude macht das Reasoning. Läuft vollständig lokal, keine API Keys, kein Cloud-Zwang.

---

## Features

- **Hybrid Search** — Vector (BGE-M3, 1024-dim, multilingual) + BM25 Keyword Search mit Reciprocal Rank Fusion (RRF)
- **8 MCP Tools** — `search_notes`, `get_similar`, `get_note_context`, `vault_stats`, `vault_health`, `reindex`, `get_config`, `update_config`
- **GraphRAG** — Wikilink-Graph mit 348+ Links, BFS-Traversal für kontextuelle Nachbarschaft
- **GARS-Scoring** — Graph-Aware Retrieval Scoring: gut vernetzte Notizen ranken höher
- **CrossEncoder Reranking** — opt-in, `BAAI/bge-reranker-v2-m3`, konfigurierbarer Score-Threshold
- **Vault Health / Gardener** — erkennt Orphan Notes, schwache Links, Stale Notes und Duplikate
- **Auto-Search** — Modi `off` / `smart` / `always` für automatische Context-Injection vor Tool-Calls
- **Heading-aware Chunking** — Semantic Context Injection (Titel, Ordner, Tags pro Chunk)
- **File Watcher** — automatische Re-Indexierung bei Vault-Änderungen via Watchdog
- **Zero Cloud** — alles lokal auf CPU, keine API Keys, keine Abhängigkeiten von externen Services

---

## Quick Start

```bash
# Install
pip install mneme

# Setup: fragt Vault-Pfad, lädt BGE-M3 (~2 GB) und baut den initialen Index
mneme setup        # oder: mneme init

# Auto-Search konfigurieren (empfohlen)
mneme auto-search smart
```

**Erster Lauf:** ~3-5 Min (Modell-Download + Index). Nachfolgende Läufe starten in unter 10s.

Fehler werden als lesbare Meldungen ausgegeben. Für vollständige Tracebacks: `MNEME_DEBUG=1 mneme <command>`.

### GPU-Support (optional)

Mneme nutzt PyTorch + sentence-transformers. Für GPU-Beschleunigung musst du torch mit passendem Accelerator **separat** installieren:

- **NVIDIA (CUDA):** `pip install torch --index-url https://download.pytorch.org/whl/cu124`
- **AMD (ROCm, Linux):** siehe [PyTorch ROCm](https://pytorch.org/get-started/locally/)
- **AMD (ROCm, Windows):** HIP SDK + spezielle Wheels nötig (~87x Speedup mit RX 7900 XTX gemessen)

Dann `mneme update-config embedding.device cuda` (bzw. `auto`).

Die `mneme[onnx]` / `[cuda]` / `[directml]`-Extras installieren den experimentellen **ONNX-Pfad** (aktuell nicht empfohlen, siehe `docs/gpu-backend-evaluation.md`).

---

## Usage with Claudian

Füge das zur `.claude/mcp.json` deines Projekts oder Vaults hinzu:

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

**Beispiel-Queries:**

- `@mneme search_notes "Zettelkasten Methode"` — semantische Suche
- `@mneme get_similar "Notiz-Titel"` — ähnliche Notizen
- `@mneme get_note_context "Notiz-Titel"` — Kontext inkl. Graph-Nachbarschaft
- `@mneme vault_health` — Vault-Diagnose (Orphans, Duplikate, Stale Notes)
- `@mneme vault_stats` — Index-Statistiken

---

## CLI Commands

| Command | Beschreibung |
|---|---|
| `mneme setup` / `mneme init` | Interaktiver Setup-Wizard |
| `mneme serve` | MCP Server starten (stdio) |
| `mneme reindex` | Inkrementelle Re-Indexierung |
| `mneme reindex --full` | Vollständige Re-Indexierung |
| `mneme status` | Index-Statistiken anzeigen |
| `mneme auto-search off` | Auto-Search deaktivieren |
| `mneme auto-search smart` | Auto-Search: nur bei relevanten Queries |
| `mneme auto-search always` | Auto-Search: immer aktiv |
| `mneme hook-search` | Intern — PreToolUse Hook für Auto-Search |
| `mneme install-hooks` | Claude Code Hooks installieren |

---

## Configuration

`mneme.toml` (wird bei `mneme setup` erstellt):

```toml
[vault]
path = "/path/to/vault"

[embedding]
provider = "sentence-transformers"
model = "BAAI/bge-m3"

[search]
vector_weight = 0.6
bm25_weight = 0.4
top_k = 10

[reranking]
enabled = false
model = "BAAI/bge-reranker-v2-m3"
threshold = 0.3

[scoring]
gars_enabled = false
graph_weight = 0.3

[auto_search]
mode = "smart"

[health]
exclude_patterns = ["Newsletter/**", "Daily Notes/**"]
```

---

## Architecture

```
Obsidian Vault (.md)
        │
        ▼
   ┌─────────┐     Watchdog
   │ Indexer  │◄──────────── File System Events
   └────┬─────┘
        │ parse, chunk, embed (BGE-M3)
        ▼
   ┌─────────┐
   │  Store   │  SQLite + sqlite-vec + FTS5 + Wikilink Graph
   └────┬─────┘
        │
        ▼
   ┌─────────┐
   │ Search   │  Hybrid → RRF → [Reranking] → [GARS]
   └────┬─────┘
        │
        ▼
   ┌──────────┐
   │ MCP      │  FastMCP (stdio) → Claudian
   │ Server   │  8 Tools
   └──────────┘
```

---

## Tech Stack

| Komponente | Technologie |
|---|---|
| Embeddings | BGE-M3 via sentence-transformers (1024-dim, multilingual) |
| Vector Store | SQLite + sqlite-vec |
| Keyword Search | SQLite FTS5 (BM25) |
| Fusion | Reciprocal Rank Fusion (RRF) |
| Graph | Wikilink-Graph, BFS-Traversal |
| Reranking | BAAI/bge-reranker-v2-m3 (opt-in, CPU) |
| MCP | FastMCP (stdio transport) |
| Config | TOML + Pydantic Settings |
| File Watching | Watchdog |

---

## License

MIT
