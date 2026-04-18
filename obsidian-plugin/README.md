# Mneme — Obsidian Plugin

Semantic vault search inside Obsidian. This plugin is the companion UI for [Mneme](https://github.com/MakaveliGER/mneme), a local MCP server for semantic search over your vault.

**What it does:**
- Starts a local Mneme HTTP server when Obsidian opens (optional, on by default)
- Adds a **Search Sidebar** for semantic + keyword search over your notes
- Shows a **"Similar Notes"** tab for whatever file you have open
- **Vault Health Modal** — find orphan notes, stale notes, duplicates, weak links
- **Status Bar** — live index stats
- Shared server with Claude Desktop / Claude Code — no duplicate process

**What it is not:** a chat UI, an LLM frontend, a cloud service. Mneme indexes and retrieves; LLMs (Claude, Cursor, ...) do the reasoning.

---

## Installation

### Option A — Pre-built release (recommended for most users)

1. Download the latest release from [github.com/MakaveliGER/mneme/releases](https://github.com/MakaveliGER/mneme/releases) — get the three files:
   - `main.js`
   - `manifest.json`
   - `styles.css`
2. Copy them into `<your-vault>/.obsidian/plugins/mneme/` (create the folder if it doesn't exist).
3. In Obsidian: **Settings → Community Plugins → Installed Plugins → Enable "Mneme"**.
4. Set the path to the Mneme CLI in the plugin settings. Typically:
   - Windows: `C:\Users\You\.mneme\.venv\Scripts\mneme.exe`
   - macOS/Linux: `/usr/local/bin/mneme` or the venv path

### Option B — Build from source

For developers or users who want the bleeding edge:

```bash
git clone https://github.com/MakaveliGER/mneme.git
cd mneme/obsidian-plugin
npm install
npm run build
# Then copy main.js + manifest.json + styles.css to <vault>/.obsidian/plugins/mneme/
```

---

## Prerequisite: Install Mneme itself

The plugin needs the Mneme Python package:

```bash
pip install obsidian-mneme
mneme setup                  # run through the wizard, choose HTTP transport
```

Full install guide and `mneme setup` details: [main README](https://github.com/MakaveliGER/mneme/blob/main/README.md).

---

## Settings

After enabling the plugin, go to **Settings → Mneme**. Key fields:

| Setting | Default | What it does |
|---|---|---|
| **Mneme Pfad** | `mneme` | Path to the CLI binary. Use the full venv path on Windows to avoid PATH issues. |
| **Auto-Start Server** | `true` | Plugin spawns `mneme serve --transport streamable-http` on Obsidian launch. |
| **Server Port** | `8765` | HTTP port. Change if 8765 is taken. |
| **Keep Server Running After Close** | `false` | When `false`, server dies with Obsidian (clean isolation). When `true`, server persists across Obsidian restarts (useful if Claude Desktop should stay warm). |
| **Reindex On Start** | `true` | Incremental re-index on Obsidian launch — catches offline edits. |
| **Embedding Device** | `auto` | `auto` / `cpu` / `cuda`. |
| **Reranking** | `off` | Opt-in. Below ~500 notes it hurts retrieval quality. |

All other settings (chunking, RRF weights, GARS) are Advanced — the defaults are tuned for vaults of 100-500 notes.

---

## Usage

**Search:**
Click the Mneme ribbon icon (Muse silhouette) to open the Search Sidebar. Type a query, press Enter. Results are hybrid (semantic + keyword) with Reciprocal Rank Fusion.

**Similar Notes:**
With any note open, switch the sidebar to the "Similar" tab. Semantic nearest-neighbours to the current file.

**Vault Health:**
Command palette → "Mneme: Vault-Health" → modal with orphans / weak-links / stale / duplicates.

**Reindex:**
Command palette → "Mneme: Reindex vault" for a manual incremental re-index. Full reindex (schema migration): do it via CLI — `mneme reindex --full`.

---

## Troubleshooting

**"Mneme nicht gefunden"** — Plugin can't find the CLI binary. Set the full path in settings (e.g. `C:\Users\You\.mneme\.venv\Scripts\mneme.exe`).

**"Pfad-Sicherheitsprüfung fehlgeschlagen"** — The plugin blocks paths whose basename isn't `mneme` / `mneme.exe`. Security feature against tampered `data.json`. Fix: use an actual Mneme binary.

**Obsidian starts slowly** — First Obsidian launch after install: the plugin waits up to 60s for the Mneme server to pre-load the BGE-M3 model (10-20s on warm disk, up to 2 min cold). Subsequent launches: nearly instant (server already warm if kept alive).

**Server won't start** — Check the path in settings. Run `<path-to>/mneme --version` in a terminal — should print a version. If not, the Python env is broken — recreate the venv.

**Port conflict** — Plugin tries port 8765 by default. If another app holds it, change **Server Port** in settings.

**Claude Desktop can't see Mneme tools** — The plugin's server and Claude Desktop are separate concerns. The plugin only starts the shared HTTP server; Claude Desktop still needs its `claude_desktop_config.json` pointing at `http://127.0.0.1:8765/mcp`. See the [main README](https://github.com/MakaveliGER/mneme/blob/main/README.md#60-sekunden-quick-start-claude-desktop).

---

## Privacy

Same as the main project: everything is local. The plugin talks to `127.0.0.1:8765` only. No telemetry, no analytics, no network calls beyond the first-time HuggingFace model download (which you can avoid by pre-populating `~/.cache/huggingface/`).

---

## License

MIT — same as the main Mneme project.
