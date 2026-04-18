<p align="center">
  <img src="https://raw.githubusercontent.com/MakaveliGER/mneme/main/design/banner.png" alt="Mneme Banner" width="100%">
</p>

# Mneme

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

**Headless RAG / Retrieval Sidecar for Obsidian.** Mneme indexiert und durchsucht deinen Vault — Claude macht das Reasoning. Läuft vollständig lokal, keine API Keys, kein Cloud-Zwang.

---

## Features

- **Hybrid Search** — Vector (BGE-M3, 1024-dim, multilingual) + BM25 Keyword Search mit Reciprocal Rank Fusion (RRF)
- **8 MCP Tools** — `search_notes`, `get_similar`, `get_note_context`, `vault_stats`, `vault_health`, `reindex`, `get_config`, `update_config`
- **3 MCP Resources + 3 MCP Prompts** — `mneme://vault/stats`, `tags`, `graph-summary` plus `research_topic`, `vault_review`, `find_connections`
- **GraphRAG** — Wikilink-Graph mit BFS-Traversal für kontextuelle Nachbarschaft
- **GARS-Scoring** — Graph-Aware Retrieval Scoring (opt-in, default off — bei <500 Notizen aktuell schädlich, siehe `docs/`)
- **CrossEncoder Reranking** — opt-in, `BAAI/bge-reranker-v2-m3` (default off — siehe Hinweis bei GARS)
- **Vault Health / Gardener** — erkennt Orphan Notes, schwache Links, Stale Notes und Duplikate
- **Auto-Search** — Modi `off` / `smart` / `always` für automatische Context-Injection vor Tool-Calls
- **Heading-aware Chunking** — Semantic Context Injection (Titel, Ordner, Tags pro Chunk)
- **File Watcher** — automatische Re-Indexierung bei Vault-Änderungen via Watchdog
- **Zero Cloud** — alles lokal (CPU oder GPU), keine API-Keys, keine externen Services

---

## Quick Start

```bash
# Install (zieht torch + sentence-transformers — initial ~1 GB Pakete + 2 GB Modell beim ersten Lauf)
pip install obsidian-mneme

# Setup: fragt Vault-Pfad, lädt BGE-M3 (~2 GB) und baut den initialen Index
mneme setup        # oder: mneme init

# Auto-Search konfigurieren (empfohlen)
mneme auto-search smart
```

> **Hinweis zu torch:** `pip install obsidian-mneme` installiert das CPU-torch-Wheel. Wenn du bereits eine CUDA-/ROCm-Variante von torch in der venv hast, überschreibt das deinen Install. Lösung: Nutze ein dediziertes venv (`uv venv` oder `python -m venv`).

**Erster Lauf (CPU):** **15-25 Min** für ~1.000 Chunks (Modell-Download ~3-5 Min + Index ~1 Chunk/s auf CPU). Mit GPU (siehe unten) unter 30 Sekunden. Nachfolgende Starts unter 10s.

Fehler werden als lesbare Meldungen ausgegeben. Für vollständige Tracebacks: `MNEME_DEBUG=1 mneme <command>`.

### GPU-Support (optional)

Mneme nutzt PyTorch + sentence-transformers. Für GPU-Beschleunigung musst du torch mit passendem Accelerator **separat** installieren:

- **NVIDIA (CUDA):** `pip install torch --index-url https://download.pytorch.org/whl/cu124`
- **AMD (ROCm, Linux):** siehe [PyTorch ROCm](https://pytorch.org/get-started/locally/)
- **AMD (ROCm, Windows):** HIP SDK + spezielle Wheels nötig (~87x Speedup mit RX 7900 XTX gemessen)

Dann `mneme update-config embedding.device cuda` (bzw. `auto`).

Die `mneme[onnx]` / `[cuda]` / `[directml]`-Extras installieren den experimentellen **ONNX-Pfad** (aktuell nicht empfohlen, siehe `docs/gpu-backend-evaluation.md`).

### Lean-install option (`raw-transformers`)

Alternative zum `sentence-transformers`-Provider: der **`raw-transformers`**-Provider nutzt direkt `transformers.AutoModel` + `torch` und braucht **kein sklearn / scipy**. Gleiche BGE-M3-Dense-Embeddings (1024-dim, CLS-Pooling, L2-normalisiert), nur ohne den Import-Overhead.

Nutzen, wenn:
- **Cold-Start** matters (sentence-transformers 5.x zieht `sklearn → scipy.special`, was auf Windows aus Electron-Subprocesses heraus langsam lädt)
- **kleinerer sdist / venv** gewünscht (sklearn + scipy = ~70 MB)
- du **Reranking/Sparse/ColBERT nicht nutzt** (Mneme's Reranking ist default-off — also: praktisch immer OK)

Umschalten:

```bash
mneme update-config embedding.provider raw-transformers
```

Oder direkt in `config.toml`:

```toml
[embedding]
provider = "raw-transformers"
```

`sentence-transformers` bleibt Default und eingebaut — kein Breaking Change.

---

## Usage mit Claude Code / Claudian

Mneme spricht [MCP](https://modelcontextprotocol.io/) über stdio. Das heißt: jeder MCP-fähige Client kann die 8 Tools nutzen. Getestet mit:

- **[Claude Code](https://claude.ai/code)** (CLI) — Konfig in `.claude/mcp.json` im Projekt- oder Vault-Ordner.
- **[Claudian](https://github.com/YishenTu/claudian)** — Obsidian-Plugin, das Claude Code im Vault verfügbar macht. Setzt dieselbe `.claude/mcp.json` voraus.

Konfig nach `pip install obsidian-mneme`:

```json
{
  "mcpServers": {
    "mneme": {
      "command": "mneme",
      "args": ["serve"]
    }
  }
}
```

Falls du stattdessen [uvx](https://docs.astral.sh/uv/) nutzt und Mneme isoliert starten willst:

```json
{ "mcpServers": { "mneme": { "command": "uvx", "args": ["mneme", "serve"] } } }
```

`uvx` installiert Mneme (und transitiv torch) in ein separates Cache-venv — größer, aber keine Kollision mit deiner Projekt-venv.

### HTTP Transport (long-running server, pre-warmed model)

Alternative zu stdio: Mneme als lokaler HTTP-Dauerläufer. Das Embedding-Modell wird **beim Serverstart** geladen (nicht beim ersten Tool-Call), jede Client-Verbindung ist sofort schnell. Sinnvoll wenn du Mneme aus mehreren Clients parallel oder zwischen Claude-Desktop-Restarts ohne Reload nutzen willst.

Start:

```bash
mneme serve --transport streamable-http
# Server lauscht auf http://127.0.0.1:8765/mcp (+ /health)
```

Port/Host lassen sich per CLI-Flag oder `config.toml` ändern:

```bash
mneme serve --transport streamable-http --host 127.0.0.1 --port 9000
```

oder persistent:

```toml
[server]
transport = "streamable-http"
host = "127.0.0.1"
port = 8765
```

Claude Desktop `mcp.json` für den HTTP-Endpoint:

```json
{
  "mcpServers": {
    "mneme": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

**Health-Check:**

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok","model_loaded":true,"db_size_mb":12.4,"init_error":null}
```

**Autostart (Windows)** — registriert einen Task-Scheduler-Eintrag beim Login:

```powershell
pwsh -File scripts/install-autostart-windows.ps1
# Deinstallieren:
pwsh -File scripts/uninstall-autostart-windows.ps1
```

Der Task startet `pythonw.exe -m mneme.cli serve --transport streamable-http` (ohne Konsolenfenster). Wenn Port 8765 kollidiert: `-Port 9000` an das Install-Skript anhängen und `config.toml` entsprechend setzen.

**Sicherheit:** Standardmäßig Loopback-only (`127.0.0.1`); FastMCP aktiviert DNS-Rebinding-Schutz automatisch. Nicht öffentlich binden — Mneme hat keine Auth.

**Beispiel-Queries:**

- `@mneme search_notes "Zettelkasten Methode"` — semantische Suche
- `@mneme get_similar "Notiz-Titel"` — ähnliche Notizen
- `@mneme get_note_context "Notiz-Titel"` — Kontext inkl. Graph-Nachbarschaft
- `@mneme vault_health` — Vault-Diagnose (Orphans, Duplikate, Stale Notes)
- `@mneme vault_stats` — Index-Statistiken

---

## Obsidian Plugin

Mneme bringt ein eigenes Obsidian-Plugin mit (`obsidian-plugin/`). Damit gibt's:

- **Search-Sidebar** — Suche im Vault aus Obsidian heraus, "Ähnliche Notizen"-Tab pro aktiver Datei
- **Health-Modal** — `vault_health` direkt aus dem Plugin
- **Status-Bar** — Index-Stats als Live-Anzeige
- **Settings** — alle Mneme-Configs, Server-Lifecycle (auto-start, Reindex-on-Start)

Das Plugin spricht die gleiche CLI an wie Claude. Voraussetzung: `mneme`-Binary im PATH (oder Pfad in den Plugin-Settings setzen). Build:

```bash
cd obsidian-plugin && npm install && npm run build
# Dann main.js + manifest.json + styles.css nach <vault>/.obsidian/plugins/mneme/ kopieren
```

Plugin-Submission an den Obsidian Community Store steht für eine spätere Version an.

---

## CLI Commands

| Command | Beschreibung |
|---|---|
| `mneme setup` / `mneme init` | Interaktiver Setup-Wizard |
| `mneme serve` | MCP Server starten (stdio, Default) |
| `mneme serve --transport streamable-http` | HTTP-Server auf 127.0.0.1:8765 (Modell pre-warmed) |
| `mneme search <query>` | Hybrid-Suche (CLI, JSON-Output) |
| `mneme similar <path>` | Semantisch ähnliche Notizen finden |
| `mneme reindex` | Inkrementelle Re-Indexierung |
| `mneme reindex --full` | Vollständige Re-Indexierung (Schema-Migration) |
| `mneme status` | Index-Statistiken anzeigen |
| `mneme health` | Vault-Diagnose (Orphans, Duplikate, Stale) |
| `mneme get-config` / `update-config` | Konfiguration lesen/schreiben |
| `mneme auto-search off/smart/always` | Auto-Search-Modus setzen |
| `mneme hook-search` | Intern — PreToolUse Hook für Auto-Search |
| `mneme install-hooks [--force]` | Claude Code Hooks installieren. `--force` umgeht den Vault-Safety-Check. |
| `mneme eval` | Retrieval-Qualität gegen Golden Dataset messen |

---

## Configuration

`mneme.toml` (wird bei `mneme setup` erstellt):

```toml
[vault]
path = "/path/to/vault"

[embedding]
provider = "sentence-transformers"   # or "raw-transformers" (lean, no sklearn/scipy) / "onnx"
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
# Beispiele — Default ist leer. Pfade per Glob, vault-relativ.
exclude_patterns = ["Newsletter/**", "Daily Notes/**"]
```

Alle Werte lassen sich auch per `mneme update-config <key> <value>` oder per Umgebungsvariable `MNEME_<SECTION>__<KEY>` (siehe `.env.example`) setzen.

---

## Troubleshooting

| Fehler | Ursache | Fix |
|---|---|---|
| `MnemeSchemaError: Legacy DB detected` | DB wurde mit einer älteren Mneme-Version gebaut | `mneme reindex --full` |
| `Failed to load sqlite-vec extension` | sqlite-vec Binary fehlt / inkompatibel mit SQLite-Version | `pip install --force-reinstall sqlite-vec` |
| `Mneme nicht gefunden: "mneme"` (Plugin) | Binary nicht im PATH | Plugin-Settings → `mnemePath` auf den vollen Pfad setzen, z.B. `.venv/Scripts/mneme.exe` |
| Modell-Download hängt auf 0% | Proxy / Firewall blockt HuggingFace | `HF_HUB_ENABLE_HF_TRANSFER=0` setzen, oder Modell manuell cachen via `HF_HOME` |
| GPU wird nicht genutzt | Dev-Env hat keinen Accelerator | Siehe "GPU-Support" oben; `mneme update-config embedding.device cuda` |
| "No vault path configured" | `mneme setup` noch nicht gelaufen | `mneme setup` oder `mneme init` |

Für die vollständige Fehlermeldung: `MNEME_DEBUG=1 mneme <command>`.

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
   │ MCP      │  FastMCP (stdio | streamable-http) → Claudian / Claude Desktop
   │ Server   │  8 Tools + /health
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
| MCP | FastMCP (stdio + streamable-http transports) |
| Config | TOML + Pydantic Settings |
| File Watching | Watchdog |

---

## License

MIT
