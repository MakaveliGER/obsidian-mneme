# Spec — Wissens-Delta-Report

**Block:** 1 (Schnellwins)
**Aufwand:** M (~1 Tag)
**Status:** draft

## Problem

Beim Session-Start nach mehreren Tagen / einer Pause hat der User **keinen Überblick** was sich im Vault geändert hat. Die manuelle Routine "Daily Notes durchscrollen + Tasks.md checken + Projekt-Status anschauen" ist teuer und wird deshalb oft übersprungen → Kontext-Verlust → später mühsame Re-Rekonstruktion.

Git liefert exakten Diff auf Textebene, aber das ist zu granular (jede Zeilenänderung, zu viele kosmetische Änderungen). Gebraucht wird ein **semantischer Überblick**: "was hat sich **inhaltlich** verändert, und wo wurden **Verbindungen** neu gebaut?"

## User Story

> Ich rufe am Montagmorgen `Mneme: Wissens-Delta seit letztem Session` auf. Mneme zeigt mir:
> - **Neu angelegt:** 3 Notizen (mit Titel + Kurz-Preview, sortiert nach Centrality)
> - **Stark bearbeitet:** 5 Notizen (>30% Content-Änderung seit letztem Check)
> - **Neue Verbindungen:** 12 Wikilinks, gruppiert nach Cluster ("Hohenstein gewinnt Verbindung zu KI-Tools")
> - **Temporal Drift:** 2 Notizen driften (Infos veraltet gegenüber neuen Nachbarn)
> Ich kann einen Zeitraum wählen (letzte 24h, 7 Tage, seit [Datum]).

## Lösung

### Baseline-Tracking
Neue DB-Tabelle `session_markers(timestamp, note_count, link_count)` — jeder `report`-Call speichert einen Marker. Delta = aktueller State − letzter Marker.

**ODER** (einfacher): Parameter `--since YYYY-MM-DD` / `--since-days N`. Kein State.

→ **Empfehlung:** kein State. User gibt Zeitraum explizit an, Default `since-days=7`. Kein "seit letztem Check"-Tracking nötig, weil User das selbst weiß ("letzte Session war Freitag").

### Datenquellen
- **Neu angelegt:** `created_at` (neue Spalte oder aus fs-ctime) ≥ cutoff
- **Stark bearbeitet:** `modified_at` (haben wir) ≥ cutoff UND signifikante Content-Änderung
  - Content-Änderung via `content_hash` (haben wir) — aber Hash ist binär "geändert ja/nein", nicht "wie viel". Brauchen Proxy: "Anzahl Chunks" geändert oder Character-Count-Diff > N
  - Im ersten Wurf: einfach `modified_at ≥ cutoff`, alle als "bearbeitet" zählen (keine Differenzierung Stark/Leicht)
- **Neue Wikilinks:** `links`-Tabelle mit `created_at`-Spalte (neu) — ODER diff gegen vorherigen Zustand via State. → Kompromiss: Link-Zeitstempel erben vom Source-Note `modified_at`
- **Temporal Drift:** aus Health-Report-Feature (wenn Block 1 sequenziell)

### Clustering von Link-Änderungen
Neue Wikilinks gruppieren nach semantischem Cluster der Source+Target-Notizen. Zeigt "Bereich X hat Y neue Verbindungen zu Z". Verhindert Flat-List von 50 Einzel-Links. **Nur wenn cluster_inbox schon gebaut** (gleiche Clustering-Infrastruktur) — sonst simpel nach Folder gruppieren.

## Interface

### MCP-Tool

```python
def knowledge_delta(
    since: str | None = None,        # ISO-Datum "2026-04-12"
    since_days: int | None = 7,      # Alternative: rollender Zeitraum
    include_drift: bool = True,      # Temporal Drift einbeziehen
) -> dict
```

Response:
```json
{
  "period": {"from": "2026-04-12", "to": "2026-04-19", "days": 7},
  "new_notes": [
    {"path": "...", "title": "...", "created_at": "...", "centrality": 0.12, "preview": "..."}
  ],
  "modified_notes": [
    {"path": "...", "title": "...", "modified_at": "...", "change_hint": "content changed"}
  ],
  "new_links": {
    "total": 12,
    "by_cluster": [
      {"cluster_theme": "Hohenstein ↔ KI-Tools", "count": 5, "examples": [...]}
    ]
  },
  "drifted_notes": [...],
  "stats": {
    "total_new": 3,
    "total_modified": 5,
    "new_link_count": 12
  }
}
```

### REST + CLI
- `POST /api/v1/knowledge-delta`
- `mneme delta --since 2026-04-12` oder `mneme delta --days 7`

### Plugin-Integration
- Neuer Command: `Mneme: Wissens-Delta zeigen`
- Optional: im Plugin-Settings ein "Show delta at Obsidian start if > 24h since last open" Toggle (opt-in)

## Daten

### Schema v4 Kandidat
- Neue Spalte `notes.created_at TEXT` — fs-ctime beim Parser. Braucht Schema-v4-Migration wie bei modified_at (v3→v4 backfill aus `min(modified_at, fs.stat().st_ctime)`).
- **ODER** Delta nutzt nur `modified_at` (was wir haben) und zeigt "neu" als "modified_at innerhalb des Zeitraums UND vorher nicht im Vault-Index". Letzteres braucht State.

→ **Empfehlung für v1:** Schema v4 mit `created_at`. Auto-Migration wie bei v2→v3. Klare Semantik statt State-Hack.

## Abhängigkeiten

- Schema v4 (created_at) — empfohlen aber nicht zwingend. Ohne created_at: Delta kann "neu vs. bearbeitet" nicht hart unterscheiden, aber funktioniert.
- **Synergie** mit Temporal Drift (aus Health-Report Stufe 2) — wenn gebaut, einbinden. Sonst Abschnitt weglassen.
- **Synergie** mit cluster_inbox — wenn gebaut, nutze Clustering für Link-Gruppierung.

## Test Plan

### Backend
- `test_knowledge_delta_new_notes`: Notizen erstellen vor vs. nach cutoff → korrekte Filterung
- `test_knowledge_delta_modified_notes`: modified_at aktualisiert → erscheint
- `test_knowledge_delta_new_links_counted`: neue Links via Indexer-Run → Counter stimmt
- `test_knowledge_delta_empty_period`: Zeitraum ohne Änderungen → saubere Empty-Response
- `test_knowledge_delta_since_days_vs_since`: beide Zeitraum-Formen konvergieren

### Plugin
- Mock-Response → Sections rendern mit Counts
- Click auf Notiz → öffnet in neuer Pane

### Live-Akzeptanz
- Nach einem Tag Pause: Delta zeigt die tatsächlich erstellten/bearbeiteten Notizen aus Daily Note
- 7-Tage-Zeitraum = guter Weekly-Review-Input

## Open Questions

1. **Schema-Change rechtfertigen:** created_at nachzurüsten ist ein Aufwand. Wert hoch genug? → Empfehlung: ja. created_at ist auch für viele Block-3-Features nützlich (Content-Recycler, Archive-Logik).
2. **Change-Hint-Granularität:** Nur "modified ja/nein", oder echter Character-Diff? → v1: nur modified ja/nein. Feineres in v2.
3. **"Starke Bearbeitung"-Schwelle:** Ab wie viel % Content-Änderung gilt Notiz als "stark bearbeitet"? → out-of-scope für v1, alles was `modified_at ≥ cutoff` hat ist "bearbeitet".

## Out-of-Scope

- **LLM-generierte Zusammenfassung** pro Delta ("hier ist dein Wochenrückblick in 3 Sätzen") — Claudian-Aufgabe, nicht Mneme.
- **E-Mail/Slack-Digest** — externes Delivery, nicht Mneme's Job.
- **Vergleich gegen beliebigen vorherigen Stand** (wie git log --since): v1 nur gegen aktuellen State.
