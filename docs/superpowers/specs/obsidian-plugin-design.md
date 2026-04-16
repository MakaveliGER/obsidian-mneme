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

| Setting | UI-Element | Config-Key | Notizen |
|---|---|---|---|
| Vault Path | Text Input (auto-detect) | `vault.path` | Auto-detect aktuellen Vault beim ersten Start |
| Embedding Model | Dropdown | `embedding.model` | BGE-M3 (Default), nomic-embed-text |
| Auto-Search Mode | Radio Group | `auto_search.mode` | Off / Smart / Always — mit Tooltips |
| Search Top-K | Number Input | `search.top_k` | Range 1–50 |
| Chunk Size | Number Input | `chunking.max_tokens` | Range 200–2000 |

#### Auto-Search Mode — Detail-Optionen

**Smart:** Zeigt Button "Regel einfügen" → ruft `mneme auto-search smart` auf, gibt Ausgabe als Notice.

**Always:** Zeigt Multi-Select "Hook Matchers" → `auto_search.hook_matchers` (Read, Bash, WebFetch, etc.)

#### Advanced Settings (hinter "Show Advanced" Toggle)

| Setting | UI-Element | Config-Key | Notizen |
|---|---|---|---|
| Reranking | Toggle + Slider | `reranking.enabled`, `reranking.threshold` | Slider Range 0.0–1.0 |
| GARS-Scoring | Toggle + Slider | `scoring.gars_enabled`, `scoring.graph_weight` | Slider Range 0.0–1.0 |
| Health Exclude Patterns | Tag-List (Add/Remove) | `health.exclude_patterns` | Freie Eingabe, Enter zum Hinzufügen |

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

`design/icon.png` (256×256 px) als Ribbon-Button in der linken Sidebar.

- Klick → öffnet/fokussiert das Sidebar Search Panel
- Tooltip: "Mneme — Vault Search"

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

Wenn Mneme mit HTTP-Transport läuft (`mneme serve --transport http`), direkter API-Zugriff statt CLI-Roundtrip. Gleiche `MnemeClient`-Schnittstelle, andere Implementierung — Plugin-Code bleibt unverändert.

---

## Zero-Config-Start

Beim ersten Plugin-Start (kein `data.json` vorhanden):

1. Auto-detect: Vault-Pfad aus Obsidian API (`vault.getRoot().path`)
2. Dialog: "Mneme gefunden? Vault indexieren?" mit Ja/Nein
3. Bei "Ja": `mneme setup --vault-path "<pfad>"` + `mneme reindex`
4. Progress-Notice während Indexierung
5. Bei Abschluss: Notice "Mneme bereit. 154 Notes indexiert."

Falls `mneme` nicht im PATH: Hinweis auf Installation (`pip install mneme` oder `uvx mneme`).

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

| Version | Inhalt |
|---|---|
| v0.1 | Settings Tab + Status Bar + Reindex Command |
| v0.2 | Search Sidebar + Command Palette (Search, Similar) |
| v0.3 | Health Modal + Zero-Config-Start-Flow |
| v1.0 | BRAT-ready, Branding poliert, Community Store Submission |
