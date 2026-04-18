<p align="center">
  <img src="https://raw.githubusercontent.com/MakaveliGER/obsidian-mneme/main/design/banner.png" alt="Obsidian Mneme Banner" width="100%">
</p>

# Obsidian Mneme

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![Platform: Windows · macOS · Linux](https://img.shields.io/badge/platform-win%20%7C%20mac%20%7C%20linux-lightgrey.svg)

**Semantische Vault-Suche für Obsidian — komplett lokal, keine API-Keys, keine Cloud.**

Obsidian Mneme indexiert deine Markdown-Notizen mit BGE-M3 (multilingual) und exponiert sie als [MCP-Server](https://modelcontextprotocol.io/). Deine Claude-Session sucht dann direkt im Vault. Daten verlassen deinen Rechner nicht.

> **Not to be confused with** [`mneme-cli`](https://pypi.org/project/mneme-cli/) by [@tolism](https://github.com/tolism/mneme) — that's an unrelated regulatory QMS tool for medical-device compliance (EU MDR / ISO 13485). This project is a semantic-search MCP server for personal Obsidian vaults. PyPI package name: **`obsidian-mneme`**.

---

## Für wen ist das?

- Du nutzt **Obsidian** mit einem wachsenden Vault und **Claude Desktop** (oder Claude Code / Cursor).
- Du willst, dass Claude deinen Vault **kennt** — nicht nur was du gerade kopierst.
- **Datenschutz ist nicht verhandelbar.** Alles bleibt auf deiner Maschine.

Mneme ist nicht: eine Cloud-SaaS-App, ein Zettelkasten, ein LLM-Frontend. Es ist ein lokaler Retrieval-Sidecar.

---

## 60-Sekunden Quick-Start (Claude Desktop)

```bash
pip install obsidian-mneme
mneme setup            # fragt Vault-Pfad, wählt Transport (http empfohlen)
mneme serve            # HTTP-Server auf http://127.0.0.1:8765/mcp
```

Dann in `%APPDATA%\Claude\claude_desktop_config.json` (oder auf macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`) den Mneme-Server eintragen:

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

**Claude Desktop komplett beenden** (System-Tray, nicht nur Fenster schließen) und neu starten. In einem neuen Chat: `@mneme search test` → Treffer aus deinem Vault.

> ⚠️ **Disk + Bandbreite:** Der erste Lauf zieht **~1 GB Python-Pakete** + **~2 GB** BGE-M3-Modell.  CPU-Erstindex auf ~200 Notizen braucht 15-25 Min (Progress-Bar sichtbar). Danach: Folgeläufe unter 10s, Queries in ~600 ms.

> ⚠️ **torch-Version:** `pip install obsidian-mneme` installiert **CPU-torch**. Wenn du schon CUDA/ROCm-torch in der venv hast, überschreibt das deinen Install. **Nimm immer ein dediziertes venv** (`python -m venv .venv` oder `uv venv`). Details siehe [GPU-Support](#gpu-support-optional).

---

## Features

- 🔒 **Zero Cloud** — alles lokal (CPU oder GPU), keine API-Keys, keine Telemetrie, kein externer Service
- 🔍 **Hybrid Search** — Vector (BGE-M3, 1024-dim, multilingual) + BM25 mit Reciprocal Rank Fusion
- 🧠 **GraphRAG** — Wikilink-Graph-Traversal für kontextuelle Nachbar-Notizen
- 🛠 **8 MCP-Tools** — `search_notes`, `get_similar`, `get_note_context`, `vault_stats`, `vault_health`, `reindex`, `get_config`, `update_config`
- 🌐 **Zwei Transport-Modi** — `stdio` für Claude Code, `streamable-http` für Claude Desktop (persistent, Model pre-warmed)
- 📊 **Vault Health** — findet Orphans, schwache Links, Stale Notes, Duplikate
- 👀 **File Watcher** — Änderungen im Vault → automatische Re-Indexierung (mit Bulk-Coalescing)
- 🔌 **Obsidian-Plugin** — Such-Sidebar, Health-Modal, Status-Bar, Auto-Start des HTTP-Servers
- 🚀 **Optional: GPU** — bis zu 87× Speedup mit ROCm/CUDA
- 🧪 **Reranking + GARS-Scoring** — opt-in, bei <500 Notizen aktuell schädlich (siehe `docs/`)

---

## Installation & Integration

Drei Clients, drei Pfade. Such dir einen aus:

### Claude Desktop (empfohlen)

→ Siehe [60-Sekunden Quick-Start](#60-sekunden-quick-start-claude-desktop) oben.

Optional als **Autostart beim Login** (kein Konsolen-Fenster):

```powershell
# Windows — registriert einen Task-Scheduler-Eintrag
pwsh -File scripts/install-autostart-windows.ps1
# Deinstallieren:
pwsh -File scripts/uninstall-autostart-windows.ps1
```

Der Task startet `pythonw.exe -m mneme.cli serve --transport streamable-http`.

### Obsidian-Plugin

Das Plugin startet den Mneme-HTTP-Server automatisch wenn Obsidian öffnet, zeigt eine Such-Sidebar, Health-Modal und Status-Bar.

**Installation:**

```
# 1. Release herunterladen: https://github.com/MakaveliGER/obsidian-mneme/releases
#    (main.js, manifest.json, styles.css)
# 2. Nach <vault>/.obsidian/plugins/mneme/ kopieren
# 3. Obsidian: Settings → Community Plugins → Mneme aktivieren
```

Oder **aus dem Source bauen** (nur wenn du selbst Änderungen machst):

```bash
cd obsidian-plugin
npm install
npm run build
# → main.js, manifest.json, styles.css nach <vault>/.obsidian/plugins/mneme/ kopieren
```

> Plugin-Submission an den Obsidian Community Store kommt in einem späteren Release.

**Was das Plugin macht:**
- Beim Obsidian-Start: spawnt `mneme serve --transport streamable-http` im Hintergrund (wenn aktiviert)
- Claude Desktop findet diesen Server dann direkt — kein manueller Serverstart nötig
- Der Server läuft nur solange Obsidian läuft (Default — per Setting änderbar)

### Claude Code (CLI)

Für Claude Code in Terminal-Sessions: stdio-Transport reicht, der Server wird pro Session gespawnt.

`.claude/mcp.json` im Vault- oder Projekt-Ordner:

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

> ⚠️ **Claude Code mit großen Python-Imports:** stdio-Transport in Electron-Kind-Prozessen kann auf Windows 60-190s hängen beim ersten Tool-Call (torch-Import). Wenn du Claude Code **und** Claude Desktop parallel nutzt, lass beide gegen den HTTP-Server laufen (siehe Quick-Start).

---

## Setup-Wizard

`mneme setup` (oder `mneme init`):

1. **Vault-Pfad** — absoluter Pfad zum Obsidian-Vault-Ordner (Beispiel: `C:\Users\You\Documents\MyVault`)
2. **Embedding-Modell** — Default `BAAI/bge-m3` (multilingual, 1024-dim, ~2 GB)
3. **Transport** — `stdio` (Default für Claude Code) oder `streamable-http` (empfohlen für Claude Desktop)
4. **Initialer Index** — läuft durch mit Progress-Bar (CPU: 15-25 Min bei 200 Notizen, GPU: <30s)

Am Ende kriegst du einen auf deinen Transport zugeschnittenen "So geht's weiter"-Hinweis.

**Version prüfen:** `mneme --version`

---

## GPU-Support (optional)

Mneme nutzt PyTorch. Für Beschleunigung **separat** installieren:

| Plattform | Befehl |
|---|---|
| NVIDIA CUDA | `pip install torch --index-url https://download.pytorch.org/whl/cu124` |
| AMD ROCm (Linux) | siehe [PyTorch ROCm](https://pytorch.org/get-started/locally/) |
| AMD ROCm (Windows) | HIP SDK + spezielle Wheels von `repo.radeon.com/rocm/windows/` |

Dann: `mneme update-config embedding.device cuda` (oder `auto`).

**Gemessen:** 87× Speedup mit RX 7900 XTX (float16, 152 Notizen, 11.9s vs 1029s CPU).

---

## Lean-Install: `raw-transformers`

Alternative zum `sentence-transformers`-Provider — nutzt direkt `transformers.AutoModel`, spart die sklearn + scipy Dependency (~70 MB). Gleiche BGE-M3-Embeddings, nur ohne Extra-Imports.

```bash
mneme update-config embedding.provider raw-transformers
```

Oder direkt in `config.toml`:

```toml
[embedding]
provider = "raw-transformers"
```

Lohnt sich wenn du kein Reranking brauchst (Default: aus) und kleinere Disk/Cold-Start-Werte willst. `sentence-transformers` bleibt der Default.

---

## Transport-Modi

| Modus | Wann? | Wie starten? |
|---|---|---|
| **`streamable-http`** | Claude Desktop, Obsidian-Plugin, mehrere Clients gleichzeitig | `mneme serve --transport streamable-http` |
| **`stdio`** | Claude Code / `.claude/mcp.json`-Workflows | `mneme serve` (Default) |

HTTP-Server lauscht auf `http://127.0.0.1:8765/mcp`, Model ist beim Start bereits geladen. Port/Host via Flag oder Config änderbar.

**Health-Check:**

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok","model_loaded":true}
```

---

## Environment-Variablen

| Variable | Zweck |
|---|---|
| `MNEME_DEBUG=1` | Aktiviert volle Tracebacks, Heartbeat-Logs, Faulthandler-Stack-Dumps |
| `MNEME_ALLOW_NETWORK=1` | Lässt HF-Hub Netzwerk-Zugriff zu (erstes Modell-Download oder Cache-Refresh) |
| `MNEME_ALLOW_NONLOOPBACK=1` | Erlaubt HTTP-Bind auf `0.0.0.0` oder andere Nicht-Loopback-Hosts (**Vault ohne Auth exponiert — nur bewusst nutzen**) |
| `HF_HOME` | Überschreibt den HuggingFace-Cache-Pfad |
| `HF_HUB_ENABLE_HF_TRANSFER=0` | Deaktiviert beschleunigte HF-Downloads (hinter Proxys manchmal nötig) |
| `MNEME_<SECTION>__<KEY>` | Beliebige Config-Felder per Env (siehe `.env.example`) |

---

## CLI-Reference

| Command | Zweck |
|---|---|
| `mneme --version` | Version anzeigen |
| `mneme setup` / `mneme init` | Interaktiver Setup-Wizard |
| `mneme serve` | MCP-Server starten (Transport aus Config) |
| `mneme serve --transport streamable-http` | HTTP-Server explizit |
| `mneme serve --port 9000 --host 127.0.0.1` | Port/Host-Override |
| `mneme search <query>` | CLI-Suche, JSON-Output |
| `mneme similar <path>` | Semantisch ähnliche Notizen |
| `mneme reindex` | Inkrementelle Re-Indexierung |
| `mneme reindex --full` | Vollständig (auch Schema-Migration) |
| `mneme status` | Index-Statistiken |
| `mneme health` | Vault-Diagnose |
| `mneme get-config` | Aktuelle Config als JSON |
| `mneme update-config <key> <value>` | Einzelnen Wert setzen |
| `mneme auto-search off/smart/always` | Auto-Search-Modus für Claude Code |
| `mneme install-hooks` | Claude-Code-Hooks installieren |
| `mneme eval` | Retrieval-Qualität gegen Golden-Dataset messen |

---

## Configuration

`config.toml` (Pfad via `mneme get-config`, typischerweise `%APPDATA%\mneme\config.toml` unter Windows):

```toml
[vault]
path = "/path/to/vault"
exclude_patterns = []  # glob, z.B. ["Newsletter/**", ".trash/**"]

[embedding]
provider = "sentence-transformers"   # oder "raw-transformers" / "onnx"
model = "BAAI/bge-m3"
device = "auto"                       # "auto" | "cpu" | "cuda"
dtype = "float16"                     # float16 (GPU) | bfloat16 (CPU) | float32
batch_size = 32

[server]
transport = "streamable-http"         # oder "stdio"
host = "127.0.0.1"
port = 8765

[search]
vector_weight = 0.6
bm25_weight = 0.4
top_k = 10

[reranking]
enabled = false
threshold = 0.3

[scoring]
gars_enabled = false
graph_weight = 0.3

[auto_search]
mode = "smart"                        # off | smart | always
```

Alle Werte auch per `mneme update-config <key> <value>` setzbar (mit Range-Validierung).

---

## FAQ

**Sendet Mneme meine Notizen an jemanden?**
Nein. Das Modell läuft lokal, der Server bindet auf `127.0.0.1`. Default ist offline (`HF_HUB_OFFLINE=1`). Einzige Netzwerk-Aktivität: HF-Hub-Download des Modells beim allerersten Lauf — danach ist alles im lokalen Cache (`HF_HOME`).

**Funktioniert Mneme ohne GPU?**
Ja. CPU reicht für den täglichen Gebrauch. Erstindex ist halt länger (15-25 Min für 200 Notizen, vs. <30s mit GPU). Queries sind mit CPU ~200-500 ms, mit GPU ~600 ms auf 5000+ Notizen.

**Was passiert wenn ich eine Notiz umbenenne?**
File-Watcher sieht's, Indexer behandelt's als delete + re-add (behält aber die DB-row-id konsistent, Wikilinks werden neu aufgelöst). Bulk-Umbenennungen (z.B. via Obsidian-Refactor): automatisches Batching.

**Kann ich Mneme für zwei Vaults parallel nutzen?**
Aktuell: ein Config-File = ein Vault. Workaround: zwei venvs mit unterschiedlichen Config-Pfaden (via `MNEME_CONFIG_PATH` env) und unterschiedlichen Ports. Multi-Vault-Support ist nicht geplant.

**Warum BGE-M3 und nicht OpenAI-Embeddings?**
BGE-M3 ist MIT-lizenziert, multilingual (inkl. Deutsch), 1024-dim, Top-Performance bei Retrieval. Keine API-Abhängigkeit, keine Kosten, kein Datenabfluss.

**Ich hatte schon torch installiert — mneme hat es überschrieben!**
Ja, das passiert wenn du in dieselbe venv `pip install obsidian-mneme` machst und torch in einer CUDA/ROCm-Variante hattest. Lösung: dediziertes venv. Siehe [GPU-Support](#gpu-support-optional).

**Claude Desktop findet keine Mneme-Tools.**
(1) Läuft der HTTP-Server? `curl http://127.0.0.1:8765/health` — muss `"status":"ok"` liefern. (2) `claude_desktop_config.json` am richtigen Ort? Windows: `%APPDATA%\Claude\`, macOS: `~/Library/Application Support/Claude/`. (3) Claude Desktop **komplett beendet** (System-Tray → Quit, nicht nur Fenster zu)?

**Port 8765 ist belegt.**
`mneme serve --port 9000` und `config.toml` oder `mcp.json` entsprechend anpassen. Mneme prüft den Port vor dem Binden und gibt eine klare Fehlermeldung.

---

## Troubleshooting

| Fehler | Ursache | Fix |
|---|---|---|
| `MnemeSchemaError: Legacy DB detected` | DB mit älterer Mneme-Version gebaut | `mneme reindex --full` |
| `Failed to load sqlite-vec extension` | sqlite-vec Binary fehlt | `pip install --force-reinstall sqlite-vec` |
| `Mneme nicht gefunden: "mneme"` (Plugin) | Binary nicht im PATH | Plugin-Settings → `mnemePath` auf vollen Pfad setzen |
| `refusing to bind to '0.0.0.0'` | Non-Loopback ohne Override | `MNEME_ALLOW_NONLOOPBACK=1` setzen — **nur wenn du weißt was du tust** |
| `port 8765 is already in use` | Anderer Prozess auf dem Port | `mneme serve --port 9000` + Config anpassen |
| Modell-Download hängt | Proxy / HF-Hub offline | `MNEME_ALLOW_NETWORK=1 mneme setup` oder `HF_HUB_ENABLE_HF_TRANSFER=0` |
| Claude Desktop zeigt keine Mneme-Tools | Server down oder Config-Ort falsch | `curl http://127.0.0.1:8765/health`; Config-Pfad prüfen; Desktop komplett beenden + neu starten |
| "No vault path configured" | `mneme setup` noch nicht gelaufen | `mneme setup` oder `mneme init` |
| GPU wird nicht genutzt | Kein Accelerator-Wheel | Siehe [GPU-Support](#gpu-support-optional) |
| Windows Defender blockt `pythonw.exe` | Behavioral Scanner bei Electron-Kind-Prozessen | Prozess-Ausnahme für den venv-`python.exe` (nicht Folder) |
| Cold-Start dauert 60-180s | Electron-spawned stdio + torch-Import | Auf HTTP-Transport umstellen (siehe Quick-Start) |

Für vollständige Tracebacks: `MNEME_DEBUG=1 mneme <command>`.

---

## Uninstall

```bash
# 1. Plugin (wenn installiert):
#    Obsidian → Settings → Community Plugins → Mneme → Uninstall
#    Dann <vault>/.obsidian/plugins/mneme/ Ordner löschen.

# 2. Autostart (wenn registriert):
pwsh -File scripts/uninstall-autostart-windows.ps1

# 3. Claude-Desktop Config: den "mneme"-Eintrag in claude_desktop_config.json entfernen.

# 4. Mneme selbst:
pip uninstall obsidian-mneme

# 5. Lokale Daten (optional):
#    Windows: %APPDATA%\mneme\  (Config + DB)
#    Windows: %LOCALAPPDATA%\huggingface\hub\  (Modell-Cache)
#    macOS:   ~/Library/Application Support/mneme/
#    Linux:   ~/.config/mneme/ + ~/.cache/huggingface/
```

---

## Architecture

```
Obsidian Vault (.md)
        │
        ▼ Watchdog (batch-coalesced)
   ┌─────────┐
   │ Indexer │   parse → chunk → embed (BGE-M3)
   └────┬────┘
        ▼
   ┌─────────┐
   │  Store  │   SQLite + sqlite-vec + FTS5 + Wikilink Graph
   └────┬────┘
        ▼
   ┌─────────┐
   │ Search  │   Hybrid → RRF → [Reranking] → [GARS]
   └────┬────┘
        ▼
   ┌──────────────────────────────────────┐
   │ MCP Server (FastMCP)                 │
   │   stdio  → Claude Code               │
   │   http   → Claude Desktop, Plugin    │
   │   REST   → Plugin-Fast-Path          │
   └──────────────────────────────────────┘
```

---

## Tech Stack

| Komponente | Technologie |
|---|---|
| Embeddings | BGE-M3 via sentence-transformers (oder raw transformers), 1024-dim, multilingual |
| Vector Store | SQLite + sqlite-vec |
| Keyword Search | SQLite FTS5 (BM25) |
| Fusion | Reciprocal Rank Fusion |
| Graph | Wikilink-Adjacency, BFS-Traversal |
| Reranking | `BAAI/bge-reranker-v2-m3` (opt-in) |
| MCP | FastMCP (stdio + streamable-http) |
| Config | TOML + Pydantic Settings |
| File Watcher | Watchdog (mit Batch-Coalescing) |
| GPU | PyTorch CUDA/ROCm (optional) |

---

## Release-Notes & Roadmap

- **Release-Historie:** siehe [CHANGELOG.md](CHANGELOG.md)
- **Offene Ideen:** Eval-Button im Plugin, `mneme doctor`-Command, Obsidian-Community-Store-Submission, Multi-Vault.

---

## License

MIT — siehe [LICENSE](LICENSE).
