# Mneme Obsidian Plugin — Design Spec

**Datum:** 2026-04-16
**Status:** Draft
**Scope:** Plugin v1 — GUI-Schicht über dem Mneme MCP-Server

---

## Problem Statement

Mneme läuft als MCP-Server und ist vollständig funktional — aber ausschließlich über Terminal bedienbar. Konfiguration erfordert manuelles Editieren der `config.toml`. Reindex, Status-Checks und Config-Änderungen setzen ein offenes Terminal voraus. Für Obsidian-User, die den Vault aktiv nutzen, ist das ein dauernder Kontextwechsel.

Das Plugin macht Mneme inside Obsidian bedienbar: kein Terminal, kein TOML-Editor — alle Kern-Interaktionen direkt in der gewohnten Arbeitsumgebung.

## Intent-Referenz

**Intent:** Mneme ist die semantische Suche im Hintergrund — das Plugin macht sie sichtbar und bedienbar, ohne den Workflow zu unterbrechen.

Jede UI-Entscheidung zahlt auf diesen Intent ein:
- **Zero-Friction:** Setup, Reindex, Suche — alles ohne Terminal
- **Non-Intrusive:** Plugin existiert, wenn man es braucht — stört nicht, wenn man es nicht braucht
- **Branding als Signal:** Mneme ist ein eigenständiges Produkt, nicht nur ein CLI-Wrapper

## Proposed Solution

### Architektur-Überblick

```
Obsidian Plugin (TypeScript)
        │
        ▼
  ┌────────────┐
  │ mneme-      │  child_process.exec() (Phase 1)
  │ client.ts   │  HTTP/SSE (Phase 2)
  └──────┬──────┘
         │
         ▼
  Mneme Backend (Python)
  MCP-Server / CLI
```

Das Plugin ist eine reine GUI-Schicht. Kein eigenes Embedding, keine eigene Suche — alles wird an den Python-Backend delegiert.

### Datei-Struktur

```
obsidian-plugin/
├── main.ts              # Plugin lifecycle, Settings registrieren, Commands, Ribbon
├── settings.ts          # Settings Tab UI
├── search-view.ts       # Sidebar Search Panel (ItemView)
├── health-modal.ts      # Vault Health Report Modal
├── status-bar.ts        # Status Bar Widget
├── mneme-client.ts      # Kommunikation mit Mneme Backend
└── styles.css           # Custom Styles (Branding-Farben)
```

---

## UI-Komponenten

### 1. Settings Tab (`settings.ts`)

Vollständige Konfiguration von Mneme über Obsidian Settings. Alle Settings werden in Obsidians `data.json` gespeichert und bei Änderung per `mneme update-config` auch in `~/.config/mneme/config.toml` geschrieben (bidirektionale Sync).

**Beim Plugin-Start:** `config.toml` lesen → Settings initialisieren.

#### Basic Settings (immer sichtbar)

Jedes Setting hat eine **Beschreibung** (`setDesc()`) die erklärt was es tut, und wo sinnvoll einen **Tooltip** mit technischen Details.

| Setting | UI-Element | Config-Key | Beschreibung |
|---|---|---|---|
| Vault Path | Text Input (auto-detect) | `vault.path` | "Pfad zum Obsidian Vault. Wird beim ersten Start automatisch erkannt." |
| Embedding Device | Dropdown | `embedding.device` | "GPU-Beschleunigung: auto erkennt GPU automatisch, cpu erzwingt CPU-Modus." |
| Embedding dtype | Dropdown | `embedding.dtype` | "Datentyp für Embeddings. float16 ist optimal für GPU (AMD), bfloat16 für CPU." |
| Auto-Search Mode | Radio Group | `auto_search.mode` | Off / Smart / Always — mit Detail-Beschreibung pro Option |
| Search Top-K | Number Input | `search.top_k` | "Anzahl der Suchergebnisse pro Abfrage (1-50)." |

#### Auto-Search Mode — Detail-Beschreibungen

| Modus | Beschreibung im Plugin |
|---|---|
| **Off** | "Mneme sucht nur wenn du oder Claude explizit `search_notes` aufruft." |
| **Smart** | "Fügt eine Regel in die CLAUDE.md ein, damit Claude bei Wissensfragen proaktiv sucht. Empfohlen." |
| **Always** | "Installiert PreToolUse-Hooks in Claudian. Claude sucht automatisch bei jedem File-Read. Maximaler Kontext, aber mehr Latenz." |

**Smart:** Zeigt Button "Regel einfügen" → ruft `mneme auto-search smart` auf, gibt Ausgabe als Notice.

**Always:** Zeigt Multi-Select "Hook Matchers" → `auto_search.hook_matchers` (Read, Bash, WebFetch, etc.)

#### Advanced Settings (hinter "Show Advanced" Toggle)

| Setting | UI-Element | Config-Key | Beschreibung |
|---|---|---|---|
| Embedding Model | Dropdown | `embedding.model` | "Embedding-Modell für Vektorsuche. BGE-M3 empfohlen (multilingual, MIT-Lizenz)." |
| Batch Size | Number Input | `embedding.batch_size` | "Batch-Größe für Embedding-Berechnung. 32 ist optimal für BGE-M3." |
| Chunk Size | Number Input | `chunking.max_tokens` | "Maximale Chunk-Größe in Tokens. Größere Chunks = mehr Kontext, weniger Precision." |
| Chunk Overlap | Number Input | `chunking.overlap_tokens` | "Überlappung zwischen Chunks in Tokens. Verhindert Informationsverlust an Chunk-Grenzen." |
| Vector Weight | Slider | `search.vector_weight` | "Gewichtung der Vektorsuche (0.0-1.0). Höher = mehr Semantik." |
| BM25 Weight | Slider | `search.bm25_weight` | "Gewichtung der Keyword-Suche (0.0-1.0). Höher = mehr exakte Matches." |
| Reranking | Toggle + Slider | `reranking.enabled`, `reranking.threshold` | "CrossEncoder Reranking für präzisere Ergebnisse. Langsamer, aber genauer. Threshold: Mindest-Score (0.0-1.0)." |
| GARS-Scoring | Toggle + Slider | `scoring.gars_enabled`, `scoring.graph_weight` | "Graph-Aware Scoring: Berücksichtigt Wikilink-Vernetzung. Gut vernetzte Notizen werden bevorzugt." |
| Health Exclude Patterns | Tag-List (Add/Remove) | `health.exclude_patterns` | "Ordner die bei Vault-Health-Checks ignoriert werden. Format: `ordner/**`" |

#### Settings-Sync-Logik

```
Plugin Start
  → config.toml lesen (via "mneme get-config")
  → Obsidian Settings initialisieren

User ändert Setting
  → data.json schreiben (Obsidian intern)
  → "mneme update-config key=value" aufrufen
  → Feedback: Notice "Config aktualisiert"
```

---

### 2. Status Bar Widget (`status-bar.ts`)

Permanent sichtbar in der Obsidian Status Bar unten rechts.

**Anzeige:**
- Grüner Punkt + `154 Notes | 1149 Chunks` — Server läuft, Index vorhanden
- Roter Punkt + `Mneme offline` — Backend nicht erreichbar

**Klick:** Öffnet ein kleines Popover (oder Modal) mit:
- Server-Status (laufend / gestoppt)
- Letzter Reindex (Timestamp)
- Index-Größe (DB in MB)
- Button "Reindex Now"

**Polling:** Status-Check alle 30 Sekunden via `mneme status`. Nur bei Statuswechsel (online→offline oder umgekehrt) Notice anzeigen.

---

### 3. Sidebar Panel — Search View (`search-view.ts`)

Obsidian `ItemView` in der linken oder rechten Sidebar. Wird via Ribbon-Button oder Command Palette geöffnet.

**Layout:**

```
┌─────────────────────────────┐
│ [Suchfeld          ] [🔍]   │
├─────────────────────────────┤
│ ERGEBNISSE                  │
│                             │
│ ┌─ Note Title ─────── 0.89 ┐│
│ │ 00 Kontext/Über mich.md  ││
│ │ Kurze Preview des Textes ││
│ └──────────────────────────┘│
│                             │
│ ┌─ Note Title ─────── 0.74 ┐│
│ │ ...                      ││
│ └──────────────────────────┘│
│                             │
├─────────────────────────────┤
│ [Search]  [Similar]         │
└─────────────────────────────┘
```

**Search-Tab:**
- Eingabe → debounced (300ms) → `mneme search "<query>"`
- Ergebnisliste: Note-Title, relativer Pfad, Score-Badge (farbkodiert), 2-Zeilen-Preview
- Klick auf Ergebnis → öffnet Note in Obsidian
- Ladeindikator während Suche läuft

**Similar-Tab:**
- Zeigt ähnliche Notes zur aktuell aktiven Note
- Wird automatisch aktualisiert wenn aktive Note wechselt (`workspace.on('active-leaf-change')`)
- Aufruf: `mneme get-similar "<aktueller-pfad>"`

**Score-Farbkodierung:**
- `≥ 0.75` → Grün (`--mneme-score-high`)
- `0.50–0.74` → Gelb (`--mneme-score-mid`)
- `< 0.50` → Rot (`--mneme-score-low`)

---

### 4. Health Modal (`health-modal.ts`)

Öffnet sich via Command `Mneme: Vault Health Check`. Ruft `mneme health` auf und zeigt den Gardener-Report.

**Sektionen:**

```
Vault Health Report          [Datum/Uhrzeit]
─────────────────────────────────────────
Orphaned Notes      12       [Liste ausklappbar]
Stale Notes         3        [Liste ausklappbar]
Missing Backlinks   7        [Liste ausklappbar]
─────────────────────────────────────────
Gesamt: 187 Notes analysiert
```

- Jede Kategorie ist ausklappbar (Disclosure Triangle)
- Klick auf Note-Pfad → öffnet die Note
- Button "Bericht exportieren" → kopiert Report als Markdown in Clipboard

---

### 5. Command Palette Commands (`main.ts`)

Alle Commands werden in `onload()` via `addCommand()` registriert.

| Command ID | Label | Aktion |
|---|---|---|
| `mneme-search` | `Mneme: Search Vault` | Öffnet Such-Modal (oder fokussiert Sidebar Such-Tab) |
| `mneme-reindex` | `Mneme: Reindex Vault` | Triggert `mneme reindex` mit Progress-Notice |
| `mneme-similar` | `Mneme: Show Similar Notes` | Öffnet Sidebar, aktiviert Similar-Tab für aktuelle Note |
| `mneme-health` | `Mneme: Vault Health Check` | Öffnet Health Modal |
| `mneme-settings` | `Mneme: Open Settings` | Öffnet Obsidian Settings → Mneme-Tab |

**Reindex-Flow:**
1. Notice: "Reindex gestartet…"
2. `mneme reindex` ausführen
3. Notice: "Reindex abgeschlossen: 154 Notes, 1149 Chunks (12.3s)"

---

### 6. Ribbon Icon (`main.ts`)

Custom SVG-Silhouette der Muse (`design/ribbon-icon.svg`) als Ribbon-Button in der linken Sidebar. Monochrom, nutzt `currentColor` für Theme-Kompatibilität (Dark + Light).

- Registriert via `addRibbonIcon()` mit inline SVG
- Klick → öffnet/fokussiert das Sidebar Search Panel
- Tooltip: "Mneme — Vault Search"

**Icon-Sichtbarkeit:**
- **Ribbon** (linke Sidebar): Custom SVG Silhouette (monochrom)
- **Plugin Settings Header**: Banner + Icon (Vollfarbe)
- **Community Plugin Store**: `icon.png` (256×256)

---

## Backend-Kommunikation (`mneme-client.ts`)

### Phase 1 — CLI-Aufrufe

Alle Backend-Operationen via `child_process.exec()`. Der `mneme`-Befehl muss im PATH verfügbar sein (oder konfigurierter Pfad).

```typescript
class MnemeClient {
  async search(query: string, topK?: number): Promise<SearchResult[]>
  async getSimilar(path: string, topK?: number): Promise<SearchResult[]>
  async getStatus(): Promise<VaultStats>
  async reindex(full?: boolean): Promise<ReindexResult>
  async healthCheck(): Promise<HealthReport>
  async getConfig(): Promise<MnemeConfig>
  async updateConfig(key: string, value: string): Promise<void>
}
```

**Error-Handling:**
- Exit-Code ≠ 0 → expliziter Error mit stderr-Inhalt
- Timeout nach 30s (Reindex: 5min)
- "mneme not found" → dedizierte Notice mit Link zu Installationsanleitung

### Phase 2 — HTTP/SSE Transport

**Shipped in v0.3.0 (2026-04-18):** Plugin auto-starts Mneme with
`mneme serve --transport streamable-http` on Obsidian launch, and Claudian /
Claude Desktop connects via `http://127.0.0.1:8765/mcp`. Plugin-internal
searches still use the CLI path — the HTTP transport exists primarily to
serve external MCP clients without paying per-session cold-start.

---

## Zero-Config-Start

Beim ersten Plugin-Start (kein `data.json` vorhanden):

1. Auto-detect: Vault-Pfad aus Obsidian API (`vault.getRoot().path`)
2. Dialog: "Mneme gefunden? Vault indexieren?" mit Ja/Nein
3. Bei "Ja": `mneme setup --vault-path "<pfad>"` + `mneme reindex`
4. Progress-Notice während Indexierung
5. Bei Abschluss: Notice "Mneme bereit. 154 Notes indexiert."

Falls `mneme` nicht im PATH: Hinweis auf Installation (`pip install obsidian-mneme`).

---

## Branding & Styles (`styles.css`)

### CSS Custom Properties

```css
:root {
  --mneme-purple: #7C3AED;
  --mneme-gold: #C9A84C;
  --mneme-dark: #1a1a2e;
  --mneme-score-high: #22c55e;
  --mneme-score-mid: #eab308;
  --mneme-score-low: #ef4444;
}
```

### Anwendung

- **Akzentfarbe** (Buttons, aktive States, Badges): `--mneme-purple`
- **Wichtige Labels / Werte** (Score-Werte, Heading in Settings): `--mneme-gold`
- **Score-Badges:** Farbkodiert via `--mneme-score-*`
- **Font** (Branding-Titel im Settings Tab): Cinzel Decorative, nur für den Plugin-Header
- **Hintergrund** (Modal-Header, Sidebar-Header): `--mneme-dark` als Akzent — nicht als Vollhintergrund, um Obsidian-Theme-Kompatibilität zu wahren

### Theme-Kompatibilität

Plugin setzt `--mneme-*` Custom Properties und nutzt ansonsten Obsidians native CSS-Variablen (`--background-primary`, `--text-normal`, etc.). Funktioniert mit Dark und Light Theme.

---

## Server-Lifecycle

### Startup (Obsidian öffnet)

```
Plugin.onload()
  → onLayoutReady()
    → autoStartServer? → spawn("mneme serve") als Hintergrund-Prozess
    → reindexOnStart? → mneme reindex (inkrementell, fängt Sync-Änderungen auf)
    → Watchdog läuft automatisch (Teil des Servers)
    → Status Bar zeigt "online"
```

### Während Nutzung

- **Watchdog** (Teil des MCP-Servers) überwacht alle Dateiänderungen live
- Jede gespeicherte Notiz → automatischer inkrementeller Reindex (~0.2s)
- Debouncing: 2 Sekunden

### Shutdown (Obsidian schließt)

```
Plugin.onunload()
  → reindexOnClose? → mneme reindex (finaler Sync)
  → Server-Prozess beenden (kill)
  → Status Bar Polling stoppen
```

### Server & Sync Settings

| Setting | Default | Beschreibung |
|---|---|---|
| Server automatisch starten | An | "Startet den Mneme-Server beim Öffnen von Obsidian. Der Server überwacht Dateiänderungen automatisch im Hintergrund (Watchdog)." |
| Reindex bei Start | An | "Synchronisiert den Index beim Öffnen. Wichtig bei Sync, Mobile, oder externen Änderungen." |
| Reindex beim Schließen | Aus | "Stellt sicher dass alle Änderungen vor dem Beenden indexiert sind." |

Info-Text: "Der Watchdog erfasst automatisch alle Dateiänderungen während Obsidian läuft. Ein manueller Reindex ist nur nötig wenn Notizen außerhalb von Obsidian geändert wurden."

---

## GPU-Support

### Für den Release

**CPU als Default** — funktioniert überall, einfache Installation (`pip install mneme`). Suche ist auch auf CPU schnell genug (75ms ohne Reranker).

**GPU als optionale Anleitung** in der Doku:
- NVIDIA: `pip install torch --index-url .../cu124` → automatisch erkannt
- AMD ROCm: HIP SDK + Python 3.12 + spezielle Wheels (Step-by-Step-Anleitung)

### Plugin-Integration

Das Plugin ruft `mneme.exe` per Pfad auf. GPU-Support ergibt sich automatisch aus der Python-Umgebung in der Mneme installiert ist:
- `mneme.exe` aus CPU-Env → CPU
- `mneme.exe` aus GPU-Env → GPU

Setting "Mneme Pfad" zeigt auf die gewünschte Installation.

### Performance-Impact

| Feature | CPU | GPU |
|---|---|---|
| Suche (ohne Reranker) | 75ms | 20ms |
| Suche (mit Reranker) | 2-5s | ~100ms |
| Full Reindex (160 Notes) | 17 Min | 12 Sek |

**Empfehlung:** Reranker nur mit GPU aktivieren. Auf CPU ist der Lag bei jeder Suche spürbar (2-5s).

---

## UX-Prinzipien

- **Zero-Config-Start:** Plugin installieren → Vault auto-detect → Index starten — kein Terminal
- **Progressive Disclosure:** Basic-Settings direkt sichtbar, Advanced-Settings hinter Toggle
- **Responsive Feedback:** Jede Aktion hat sichtbares Feedback — Ladeindikator, Notice, Fehlermeldung
- **Explizite Errors:** Kein Silent Fail. Wenn Backend nicht erreichbar: klare Meldung + nächster Schritt
- **Non-Intrusive:** Status Bar ist permanent aber klein. Kein Auto-Popup, kein erzwungener Onboarding-Flow

---

## Tech Stack

| Komponente | Technologie | Begründung |
|---|---|---|
| Plugin Runtime | TypeScript + Obsidian API | Standard für Obsidian Plugins |
| Backend-Kommunikation (Phase 1) | `child_process.exec` | Einfachste Integration ohne Server-Änderungen |
| Backend-Kommunikation (Phase 2) | `fetch` + SSE | Direkter API-Zugriff, niedrigere Latenz |
| Settings Storage | Obsidian `data.json` | Vault-lokal, automatisch gespeichert |
| Config-Sync | `mneme update-config` CLI | Kein direktes TOML-Schreiben im Plugin |
| Build | esbuild | Standard Obsidian Plugin Build-Setup |
| Distribution | BRAT → Community Store | Erst Beta-Kanal, dann offiziell |

---

## Out of Scope (Plugin v1)

| Was | Warum nicht |
|---|---|
| Eigenes Embedding im Plugin | Alles über Backend — kein Python in TypeScript |
| Graph-Visualisierung | Scope-Creep, nicht im Intent |
| Multi-Vault-Support | Komplexität nicht gerechtfertigt in v1 |
| Mobile Support (Obsidian Mobile) | `child_process` nicht verfügbar auf Mobile |
| Eigene Wikilink-Auflösung | Bereits im Backend |

---

## Roadmap

| Version | Inhalt | Status |
|---|---|---|
| v0.1 | Settings Tab + Status Bar + Reindex Command + Server-Lifecycle | ✅ Gebaut |
| v0.2 | Search Sidebar + Command Palette (Search, Similar) | ✅ Gebaut |
| v0.3 | Health Modal + Custom Ribbon Icon (Muse SVG) | ✅ Gebaut |
| v0.4 | GPU-Settings + Query Expansion + Sync-Settings | ✅ Gebaut |
| v0.5 | In Obsidian testen, Bugs fixen, Polish | ⬚ Next |
| v1.0 | BRAT-ready, README, Community Store Submission | ⬚ |

## Implementation Status (2026-04-17)

Alle UI-Komponenten gebaut, TypeScript kompiliert fehlerfrei, 24 KB Bundle.

| Datei | Beschreibung | LOC |
|---|---|---|
| `main.ts` | Plugin lifecycle, ribbon, commands, server start/stop | ~190 |
| `settings.ts` | Vollständige Settings mit deutschen Beschreibungen | ~500 |
| `search-view.ts` | Sidebar mit Search + Similar-Tab | ~220 |
| `health-modal.ts` | Vault Health Report Modal | ~130 |
| `status-bar.ts` | Online/Offline Status + Polling | ~55 |
| `mneme-client.ts` | CLI-Kommunikation + Server-Management | ~170 |
| `types.ts` | Interfaces + Defaults | ~130 |
| `styles.css` | Branding + Theme-Kompatibilität | ~200 |
