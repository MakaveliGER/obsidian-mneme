# Spec — Duplikat-Warnung

**Block:** 1 (Schnellwins)
**Aufwand:** S (2-4h)
**Status:** draft

## Problem

Beim Anlegen einer neuen Notiz passiert es regelmäßig, dass es bereits eine **semantisch sehr ähnliche Notiz** im Vault gibt — dem Nutzer aber nicht präsent. Folge: Vault-Fragmentierung, redundante Einträge zum selben Thema, gebrochene Verlinkungen weil die "richtige" Notiz nicht gefunden wurde.

Konkretes Beispiel: Nutzer legt `RAG-Evaluation.md` an — wusste nicht dass `Retrieval-Augmented-Generation Testing.md` schon existiert.

## User Story

> Wenn ich eine neue Notiz anlege (Titel eingegeben, vielleicht erste Zeilen getippt) und **zum ersten Mal speichere**, soll Mneme mir eine Notice zeigen: "Sehr ähnliche Notiz existiert bereits: [[X]] (87% Ähnlichkeit). Erweitern statt neu anlegen?" Ich kann die Warnung wegklicken oder zur vorhandenen Notiz springen.

## Lösung

### Trigger
Plugin-Hook auf `vault.on("create")` **ODER** auf `metadataCache.on("changed")` beim ersten Save einer neuen Datei (Heuristik: Notiz < N Sekunden alt).

### Flow
1. Neue Datei wird erstellt/erstmals gespeichert.
2. Plugin extrahiert Titel + erste ~500 Zeichen Body.
3. Ruft `POST /api/v1/duplicate-check` mit diesem Text.
4. Backend berechnet Embedding, sucht Top-3 ähnliche Notizen ohne die neue selbst.
5. Wenn Top-Treffer Similarity > Threshold (default 0.75): Obsidian-Notice mit Link.

### UI
- Obsidian-Notice (10 Sekunden sichtbar) — **nicht** Modal (intrusiv beim Schreibfluss).
- Text: `"⚠️ Ähnliche Notiz: [[{title}]] ({pct}% Match). Klicken zum Öffnen."`
- Click auf Notice → öffnet die bestehende Notiz in neuem Pane (Split-View), neue Notiz bleibt aktiv.

## Interface

### Neuer REST-Endpoint (fast-path)

```
POST /api/v1/duplicate-check
{
  "title": "RAG-Evaluation",
  "content": "Erste Zeilen der neuen Notiz...",
  "exclude_path": "02 Projekte/RAG-Evaluation.md",
  "threshold": 0.75,
  "top_k": 3
}
```

Response:
```json
{
  "matches": [
    {"path": "...", "title": "...", "similarity": 0.87, "relevance_pct": 100}
  ],
  "total_candidates_scanned": 150
}
```

### Neues MCP-Tool (optional für Claudian-Use-Cases)

```python
def check_duplicate(title: str, content: str, threshold: float = 0.75) -> dict
```

Gleiche Semantik. Wird nicht primär vom Plugin genutzt (REST ist schneller), aber für Claude-initiated Use-Cases verfügbar.

### Plugin

- Neuer Setting: `duplicateCheckEnabled: boolean` (default true)
- Neuer Setting: `duplicateCheckThreshold: number` (default 0.75, Slider 0.5-0.95)
- Neuer Setting: `duplicateCheckMinCharacters: number` (default 50) — unterdrückt den Check bei fast leeren Notizen

## Daten

**Keine Schema-Änderung.** Nutzt bestehendes Embedding + Store.search.

## Abhängigkeiten

Keine. Standalone baubar.

## Test Plan

### Backend (pytest)
- `test_duplicate_check_finds_near_match`: Zwei sehr ähnliche Notizen → erste findet zweite
- `test_duplicate_check_exclude_path`: Anfragende Notiz ist nie im Ergebnis
- `test_duplicate_check_below_threshold_returns_empty`: Entfernte Notizen → leeres Ergebnis
- `test_duplicate_check_content_prefix`: Kurzer Text (Title only) vs. langer Text — both work

### Plugin (vitest)
- Mock duplicate-check response → Notice wird erstellt mit richtigem Text
- Empty matches → keine Notice
- `duplicateCheckMinCharacters` Guard → kurze Content = skip

### Live-Akzeptanz
- Neue Notiz `"RAG Evaluation"` anlegen → Notice zeigt existierende RAG-Notizen
- Neue Notiz `"Rezept Spaghetti Carbonara"` anlegen → keine Notice (kein Match im Vault)

## Open Questions

1. **Trigger-Timing:** Nur beim Create, oder auch wenn Notiz leer war und dann Content bekommt? → Empfehlung: beides, mit Debounce (nur einmal pro Notiz in ersten 60s).
2. **False-Positive-Suppression:** Wenn User die Notice wegklickt, soll der Check für diese Notiz für immer deaktiviert werden? → Empfehlung: ja, via Frontmatter-Flag `mneme: {duplicate_check: dismissed}`.
3. **Threshold-Default:** 0.75 ist Schätzung. Nach Live-Test evtl. anpassen (eher Richtung 0.8 wenn zu viele False-Positives).

## Out-of-Scope

- Automatisches Mergen von Duplikaten (→ Block-3 Vault-Write-Features).
- Vorschläge "Erweitere existierende Notiz um diesen neuen Content" (→ Auto-Link on Create deckt einen Teil ab).
