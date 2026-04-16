# Mneme — Design Spec

**Datum:** 2026-04-16
**Status:** Draft
**Scope:** Phase 1 (MVP) — Erweiterungspunkte für Phase 2+3 definiert

---

## Problem Statement

Claude in Claudian findet Vault-Notizen nur über Grep/Glob (exakte String-Matches). Bei ~300+ Notizen mit wachsender Vernetzung wird das zum Bottleneck: semantisch verwandte Notizen bleiben unsichtbar, wenn der exakte Suchbegriff nicht vorkommt.

## Intent-Referenz

**Intent:** Semantische Vault-Suche als lokaler MCP-Server — Claude fragt, Mneme liefert die relevanten Notizen.

Jede Architekturentscheidung muss auf diesen Intent einzahlen:
- **Hybrid Search** → findet Notizen auch ohne exakte Keyword-Treffer
- **MCP-Integration** → nahtlos in Claudian, kein Extra-Interface
- **Lokal** → keine Cloud-Abhängigkeit, keine Kosten, Privacy
- **Headless** → kein eigenes LLM, Claude übernimmt das Reasoning

## Proposed Solution

### Architektur-Überblick

```
Obsidian Vault (Markdown)
        │
        ▼
   ┌─────────┐     Watchdog
   │ Indexer  │◄──────────── File System Events
   └────┬─────┘
        │ parse, chunk, embed
        ▼
   ┌─────────┐
   │  Store   │  SQLite + sqlite-vec + FTS5
   └────┬─────┘
        │
        ▼
   ┌─────────┐
   │ Search   │  Hybrid (Vector + BM25) → RRF
   └────┬─────┘
        │
        ▼
   ┌──────────┐
   │ MCP      │  FastMCP (stdio) → Claudian
   │ Server   │  6 Tools
   └──────────┘
```

### Komponenten

#### 1. Config (`mneme/config.py`)

**Pydantic Settings** mit TOML-Backend. Drei Quellen (Priorität absteigend):
1. Environment Variables (`MNEME_VAULT_PATH`, etc.)
2. Config-Datei (via `platformdirs`: Windows `%APPDATA%/mneme/config.toml`, Linux `~/.config/mneme/config.toml`)
3. Defaults

```toml
[vault]
path = "D:\\Vault\\second-brain\\second-brain"
glob_patterns = ["**/*.md"]
exclude_patterns = [".obsidian/**", ".trash/**"]

[embedding]
provider = "sentence-transformers"
model = "BAAI/bge-m3"
# dimensions wird vom Modell bestimmt (BGE-M3: 1024)

[chunking]
strategy = "heading"          # heading-aware splitting
max_tokens = 1000
overlap_tokens = 100

[search]
vector_weight = 0.6
bm25_weight = 0.4
top_k = 10
# Phase 2: reranker, rerank_threshold
# Phase 3: gars_enabled, graph_weight

[database]
# Pfad via platformdirs: Windows %LOCALAPPDATA%/mneme/, Linux ~/.local/share/mneme/
path = ""  # Default: platformdirs.user_data_dir("mneme") / "mneme.db"

[server]
transport = "stdio"
```

**Setup-Wizard** (`mneme setup`): Interaktiver CLI-Wizard, der `config.toml` erstellt und den initialen Index baut.

**Erweiterungspunkt Phase 2+3:** Neue Config-Sections (`[reranking]`, `[graph]`) addieren sich — bestehende Config bleibt unverändert.

#### 2. Markdown Parser (`mneme/parser.py`)

Verantwortlich für:
- **Frontmatter-Extraktion** — YAML zwischen `---` Delimitern → `dict`
- **Wikilink-Erkennung** — Regex `\[\[([^\]|]+)(?:\|[^\]]+)?\]\]` → Capture Group 1 = Link-Target. Obsidian-Format `[[Ziel|Alias]]` wird korrekt aufgelöst: nur `Ziel` wird als Link-Target extrahiert, `Alias` verworfen. In Phase 1 nur extrahiert und als Metadaten gespeichert, nicht aufgelöst.
- **Tag-Parsing** — aus Frontmatter (`tags:`) und Inline (`#tag`)
- **Heading-aware Chunking** — Split an `##`+ Headings, jeder Chunk behält den Heading-Pfad

**Semantic Context Injection** — jeder Chunk bekommt einen Header:
```
[Title: Über mich | Folder: 00 Kontext | Tags: kontext]

## Werte und Positionierung
Was mich auszeichnet: die seltene Kombination aus ...
```

Das gibt dem Embedding-Modell Kontext über die Herkunft des Chunks, ohne dass der Chunk isoliert im Vektorraum steht.

**Chunking-Regeln:**
1. Split an `##`+ Headings
2. Heading-Pfad akkumulieren: `# Über mich > ## Tech-Stack`
3. Wenn Section > `max_tokens`: Split an Absätzen (Doppel-Newline)
4. Overlap: letzte `overlap_tokens` Tokens vom Vorgänger-Chunk prependen
5. Sehr kurze Sections (< 50 Tokens) mit nächster Section mergen

**Erweiterungspunkt Phase 2:** Wikilinks werden in Phase 1 bereits extrahiert. Phase 2 baut daraus den Graph.

#### 3. Embedding Provider (`mneme/embeddings/`)

**Abstract Base Class:**
```python
class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch-Embedding. Returns list of vectors."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension of this model."""
        ...
```

**Phase 1 Implementation:** `SentenceTransformersProvider`
- Modell: `BAAI/bge-m3` (1024 Dimensionen)
- Batch-Processing für Indexierung
- Lazy Loading: Modell erst bei erstem Aufruf laden

**Erweiterungspunkt Phase 2+3:** `OllamaProvider`, `ONNXProvider` — gleiche Schnittstelle, andere Runtime. Config-Switch: `embedding.provider`.

#### 4. Store (`mneme/store.py`)

**Einzige SQLite-Datenbank** — Vektoren, Volltext und Metadaten am selben Ort.

**Schema:**

```sql
-- Notizen (eine Zeile pro Markdown-Datei)
CREATE TABLE notes (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,     -- relativer Pfad im Vault
    title       TEXT,
    content_hash TEXT NOT NULL,           -- SHA-256 des Dateiinhalts
    frontmatter TEXT,                     -- JSON-serialisiert
    tags        TEXT,                     -- JSON-Array, denormalisiert für schnellen Zugriff
    wikilinks   TEXT,                     -- JSON-Array der extrahierten [[Links]]
    updated_at  TEXT NOT NULL             -- ISO 8601
);

-- Chunks (N pro Notiz)
CREATE TABLE chunks (
    id          INTEGER PRIMARY KEY,
    note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,            -- Chunk-Text inkl. Context Header
    heading_path TEXT,                    -- z.B. "# Über mich > ## Tech-Stack"
    chunk_index INTEGER NOT NULL,        -- Position innerhalb der Notiz
    UNIQUE(note_id, chunk_index)
);

-- FTS5 Virtual Table für BM25
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    content,
    content=chunks,
    content_rowid=id,
    tokenize='unicode61'
);

-- sqlite-vec Virtual Table für Vektor-Suche (einziger Speicherort der Vektoren)
-- Erstellt dynamisch basierend auf Embedding-Dimension
CREATE VIRTUAL TABLE chunks_vec USING vec0(
    chunk_id INTEGER PRIMARY KEY,    -- referenziert chunks.id
    embedding float[1024]
);
```

**Trigger für FTS5-Sync:**
```sql
-- Insert/Update/Delete Trigger halten chunks_fts synchron mit chunks
```

**Methoden:**
- `upsert_note(path, title, content_hash, frontmatter, tags, wikilinks)` → note_id
- `upsert_chunks(note_id, chunks: list[ChunkData])` — löscht alte Chunks der Notiz, fügt neue ein
- `delete_note(path)` — CASCADE löscht auch Chunks
- `get_note_by_path(path)` → Note | None
- `vector_search(query_embedding, top_k)` → list[SearchResult]
- `bm25_search(query_text, top_k)` → list[SearchResult]
- `get_stats()` → IndexStats

**Erweiterungspunkt Phase 2:** `links`-Table für Wikilink-Graph (Adjacency List):
```sql
CREATE TABLE links (
    source_id INTEGER REFERENCES notes(id),
    target_id INTEGER REFERENCES notes(id),
    PRIMARY KEY (source_id, target_id)
);
```

#### 5. Search (`mneme/search.py`)

**Hybrid Search Pipeline:**

```
Query
  ├──► Embed Query ──► Vector Search (top_k * 3) ──► Post-Filter ──┐
  │                                                                  ├──► RRF Fusion ──► Results
  └──► BM25 Search (top_k * 2, pre-filtered) ─────────────────────┘
```

**Reciprocal Rank Fusion (RRF):**
```
RRF_score(d) = Σ 1/(k + rank_i(d))    wobei k = 60
```

Jedes Ergebnis bekommt einen RRF-Score aus seiner Position in beiden Ergebnislisten. Dokumente die in beiden Listen auftauchen, werden bevorzugt.

**Over-Retrieval:** BM25 liefert `top_k * 2`, Vector Search liefert `top_k * 3` (höherer Faktor wegen Post-Filtering). RRF schneidet auf `top_k` ab.

**Filter:** Optional einschränken auf:
- `tags: list[str]` — Notiz muss mindestens einen der Tags haben
- `folders: list[str]` — Pfad muss mit einem der Folder-Präfixe beginnen
- `after: date` — `updated_at` nach Datum

**Filtering-Strategie (sqlite-vec Constraint):**
- **BM25 (FTS5):** Pre-Filtering via SQL JOIN auf `notes`-Tabelle — WHERE-Klausel auf Tags/Folder/Datum, dann FTS5-Match.
- **Vector Search (sqlite-vec):** sqlite-vec KNN-Queries unterstützen **keine WHERE-Klausel**. Deshalb: Over-Retrieval (`top_k * 3`), dann Post-Filtering der Ergebnisse über JOIN mit `chunks` → `notes` Metadaten. Falls nach Post-Filtering weniger als `top_k` Ergebnisse übrig → akzeptieren (besser wenige relevante als irrelevante auffüllen).

**Erweiterungspunkt Phase 2:** Reranker-Step nach RRF:
```
... ──► RRF Fusion ──► Reranker (CrossEncoder) ──► Score Filter (< 0.3) ──► Results
```

**Erweiterungspunkt Phase 3:** GARS-Scoring multipliziert RRF-Score mit Graph-Zentralität.

#### 6. Indexer (`mneme/indexer.py`)

**Zwei Modi:**

**Full Index** (`reindex --full`):
1. Alle `.md` Dateien im Vault scannen (glob_patterns, exclude_patterns)
2. Für jede Datei: parsen → chunken → embedden → store
3. Verwaiste Notizen in DB löschen (Datei existiert nicht mehr)

**Incremental Index** (Default bei `reindex` und File Watcher):
1. Datei scannen → `content_hash` berechnen
2. Hash mit DB vergleichen → nur geänderte Dateien re-indexieren
3. Gelöschte Dateien aus DB entfernen

**Batch-Embedding:** Chunks werden in Batches an den Embedding-Provider geschickt (batch_size aus Config, Default 32).

**Erweiterungspunkt Phase 2:** Nach dem Indexieren Wikilinks auflösen und `links`-Table befüllen.

#### 7. File Watcher (`mneme/watcher.py`)

**Watchdog** Observer auf dem Vault-Verzeichnis:
- `FileCreatedEvent` / `FileModifiedEvent` → Incremental Index für die Datei
- `FileDeletedEvent` → Note aus DB löschen
- `FileMovedEvent` → Path in DB aktualisieren

**Debouncing:** Obsidian schreibt Dateien manchmal mehrfach kurz hintereinander (Auto-Save). Events für dieselbe Datei innerhalb von 2 Sekunden zusammenfassen.

**Filter:** Nur `.md` Dateien, nur innerhalb glob_patterns, nicht in exclude_patterns.

#### 8. MCP Server (`mneme/server.py`)

**FastMCP** mit stdio-Transport. Tool-Definitionen:

| Tool | Parameter | Return |
|---|---|---|
| `search_notes` | `query: str`, `top_k?: int`, `tags?: list[str]`, `folders?: list[str]`, `after?: str` | Liste von `{path, title, content, heading_path, score}` |
| `get_similar` | `path: str`, `top_k?: int` | Liste von `{path, title, score}` |
| `vault_stats` | — | `{total_notes, total_chunks, last_indexed, embedding_model, db_size_mb}` |
| `reindex` | `full?: bool` | `{indexed, skipped, deleted, duration_seconds}` |
| `get_config` | — | Aktuelle Config als Dict |
| `update_config` | `key: str`, `value: str` | `{updated_key, old_value, new_value}` |

**`search_notes` Response-Format** (an Claude optimiert):
```json
{
  "results": [
    {
      "path": "00 Kontext/Über mich.md",
      "title": "Über mich",
      "heading_path": "# Über mich > ## Fachgebiete",
      "content": "[Chunk-Text, max 1500 Zeichen]",
      "score": 0.82,
      "tags": ["kontext"]
    }
  ],
  "query": "KI-Consulting Erfahrung",
  "total_results": 3,
  "search_time_ms": 145
}
```

**`get_similar`:** Nimmt den Durchschnittsvektor aller Chunks einer Notiz und sucht ähnliche Notizen (nicht Chunks). Nützlich für "was hängt mit dieser Notiz zusammen?".

**Erweiterungspunkt Phase 2:** `get_note_context` Tool (Notiz + Graph-Nachbarn + Similar als Bundle).

### CLI

```
mneme setup     # Interaktiver Wizard → erstellt config.toml + initialer Index
mneme serve     # MCP-Server starten (stdio)
mneme reindex   # Manueller Reindex (--full für komplett)
mneme status    # Index-Statistiken anzeigen
```

Entry Point via `pyproject.toml`:
```toml
[project.scripts]
mneme = "mneme.cli:main"
```

Distribution via PyPI → `uvx mneme serve` funktioniert ohne lokale Installation.

### Paket-Struktur

```
src/mneme/
├── __init__.py
├── __main__.py              # python -m mneme
├── cli.py                   # Click CLI (setup, serve, reindex, status)
├── config.py                # MnemeConfig (Pydantic Settings + TOML)
├── parser.py                # Markdown-Parsing, Chunking, Context Injection
├── store.py                 # SQLite + sqlite-vec + FTS5
├── search.py                # Hybrid Search + RRF
├── indexer.py               # Full + Incremental Indexing
├── watcher.py               # Watchdog File Watcher
├── server.py                # FastMCP Server + Tool-Definitionen
└── embeddings/
    ├── __init__.py           # get_provider() Factory
    ├── base.py               # EmbeddingProvider ABC
    └── sentence_transformers.py  # BGE-M3 Implementation
```

## Tech Stack

| Komponente | Technologie | Version | Begründung |
|---|---|---|---|
| Runtime | Python | 3.11+ | Breite Library-Kompatibilität |
| MCP Framework | FastMCP | latest | Offizielle Python MCP-Lib, stdio-Support |
| Vector Store | sqlite-vec | latest | Zero-Config, embedded, Cosine Distance |
| Keyword Search | SQLite FTS5 | built-in | BM25 im selben DB-File |
| Embeddings | sentence-transformers | latest | BGE-M3 Support, Batch-Processing |
| Embedding Model | BAAI/bge-m3 | latest | Multilingual, 1024 Dim, State-of-the-Art |
| Config | Pydantic Settings | v2 | Validation, TOML-Support, Type Safety |
| CLI | Click | latest | Standard für Python CLIs |
| File Watcher | Watchdog | latest | Cross-Platform, bewährt |
| Pfade | platformdirs | latest | Cross-Platform Config/Data-Pfade |
| YAML Parsing | PyYAML / ruamel.yaml | latest | Frontmatter |
| Package Manager | uv | latest | Schnelle Auflösung, Lock-File |
| Distribution | PyPI + uvx | — | Isolierte Ausführung ohne globale Installation |

## Out of Scope (Phase 1)

| Was | Warum nicht | Wann |
|---|---|---|
| CrossEncoder Reranking | Zusätzliche Latenz + Dependency, MVP-Qualität erst messen | Phase 2 |
| Wikilink-Graph / GraphRAG | Braucht funktionierenden Index als Basis | Phase 2 |
| Alias-Map für Wikilinks | Teil von GraphRAG | Phase 2 |
| GARS-Scoring | Braucht Graph aus Phase 2 | Phase 3 |
| Obsidian-Plugin | MCP-Server muss erst stabil laufen | Phase 3 |
| LLM-Provider (Standalone) | Headless Sidecar ist der Hauptanwendungsfall | Phase 3 |
| Slim-Sync (Hot/Cold Store) | content_hash für Incremental Index ist in Phase 1, Vault Intelligence-Style Slim-Sync ist Optimierung | Phase 3 |
| HTTP/SSE Transport | stdio reicht für Claudian, HTTP nur für Multi-Client | Phase 3 |
