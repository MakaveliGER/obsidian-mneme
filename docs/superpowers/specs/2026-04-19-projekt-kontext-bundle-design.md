# Spec — Projekt-Kontext-Bundle

**Block:** 2 (Daily-PKM-Power)
**Aufwand:** M (~1 Tag)
**Status:** draft

## Problem

Beim Öffnen einer **Projekt-Notiz** (z.B. `Mneme.md`, `Argus.md`, `Hohenstein.md`) müssten **alle semantisch verwandten Ressourcen** sofort sichtbar sein — ohne manuelles Suchen. Aktuell:
- Wikilinks zeigen nur **explizit verlinkte** Notizen (typisch 3-8)
- Semantisch verwandte aber unverlinkte Notizen (~20-40 pro Projekt) bleiben unsichtbar
- User müsste pro Projekt-Öffnen eine Search ausführen, macht er nicht routinemäßig

Ergebnis: Projekte laufen auf 10% der verfügbaren Kontext-Information.

**Beschrieb im Brainstorming als "mächtigste Einzelfunktion"** — weil es jede Projektarbeit spürbar mit Vault-Wissen anreichert.

## User Story

> Ich öffne `Mneme.md`. Ein Plugin-Panel rechts zeigt automatisch:
> - **Explizit verlinkt** (Wikilink-aus-Ziel): 8 Notizen (wie bisher)
> - **Semantisch verwandt, NICHT verlinkt** (neu): 15-25 Notizen gruppiert nach Typ — `Tools (4)`, `Workflows (3)`, `Ressourcen (8)`, `Andere Projekte (2)`
> - Jede Gruppe collapsible. Click auf Notiz → öffnet in neuer Pane, aktive bleibt.
> - Pro Notiz: Titel + Relevance-% + Snippet

## Lösung

### Trigger
**Plugin-Hook:** `workspace.on("active-leaf-change")` — wenn neue Notiz aktiv wird.
- Debounce 500ms (verhindert Flackern beim schnellen Tab-Wechsel)
- Guard: nur aktiv wenn aktuelle Notiz ein "Projekt" ist (Heuristik: Frontmatter `projekttyp` ODER Pfad unter `02 Projekte/` ODER User-Setting "alle Notizen")

### Backend-Flow
1. Plugin sendet Pfad + (optional) Content-Hash
2. Backend: `get_similar(path, top_k=30)` — großzügige Candidate-Menge
3. Backend: lädt `links`-Tabelle für diese Notiz → `already_linked_paths`-Set
4. Filter: `similar - already_linked` = semantically-related-but-unlinked
5. Optional: Gruppierung nach Ordner-Prefix (erste Ordner-Ebene) oder Frontmatter-`projekttyp`
6. Response mit **beiden Listen** (explicit_links + semantic_neighbors) — Plugin rendert beide Sektionen

### UI
Neues Plugin-View: `Mneme: Kontext` (zweiter Sidebar-Tab neben Suche).
- Auto-Update bei Notiz-Wechsel
- Manueller Refresh-Button
- Settings-Toggle: "Nur für Projekte aktivieren" (default true)

### Performance
- HTTP-Fast-Path (10ms) ist schnell genug für Auto-Trigger
- Cache: Content-Hash-gleich → Response aus Plugin-Memory-Cache. Verhindert Requests beim Pane-Toggle.

## Interface

### MCP-Tool

```python
def get_project_context(
    path: str,
    top_k: int = 30,
    group_by: str = "folder",  # "folder" | "projekttyp" | "flat"
    include_linked: bool = True,
) -> dict
```

Response:
```json
{
  "target": {"path": "...", "title": "Mneme"},
  "explicit_links": {
    "out": [{"path": "...", "title": "..."}],
    "in": [{"path": "...", "title": "..."}]
  },
  "semantic_neighbors": {
    "total": 22,
    "groups": [
      {
        "group_label": "04 Ressourcen",
        "items": [
          {"path": "...", "title": "...", "similarity": 0.81, "relevance_pct": 100, "content": "snippet"}
        ]
      }
    ]
  },
  "stats": {"candidates_scanned": 30, "already_linked_filtered": 8}
}
```

### REST + CLI
- `POST /api/v1/project-context`
- `mneme context-bundle <path>` (unterscheidet sich von `mneme context` aus Session-Restore — bewusst: zwei verschiedene Features, zwei Commands)

### Plugin
- Neuer View `mneme-context-view` — Sidebar-Tab
- Auto-Fetch bei `active-leaf-change`
- Konfig: `projectContextAutoTrigger`, `projectContextScope` ("projects-only" | "all-notes" | "off")

## Daten

Keine Schema-Änderung. Reuse von `get_similar` + `links`-Tabelle.

## Abhängigkeiten

- Keine Feature-Abhängigkeiten.
- **Synergie** mit Auto-Link on Create: beides nutzt "similar - already_linked"-Pattern. **Empfehlung: gleichen Backend-Helper bauen** (`mneme.search.get_unlinked_similar(path, top_k)`) — spart Duplikation.

## Test Plan

### Backend
- `test_project_context_filters_existing_links`: Similar mit Link → nicht in semantic_neighbors
- `test_project_context_includes_bidirectional_links`: Out- und In-Links beide in explicit_links
- `test_project_context_group_by_folder`: Gruppierung nach erster Ordner-Ebene
- `test_project_context_empty_when_no_similar`: Isolierte Notiz → leere semantic_neighbors

### Plugin
- Mock-Response → View rendert beide Sektionen korrekt
- Auto-Trigger: neue Active-Leaf → Request mit neuem Pfad
- Cache: zweiter Trigger auf gleiche Notiz → kein Request
- "projects-only" Guard: Nicht-Projekt-Notiz → View zeigt Hinweis, kein Request

### Live-Akzeptanz
- `Mneme.md` öffnen → Panel zeigt sinnvolle 15-25 verwandte Notizen, gruppiert
- Wechsel zu `Argus.md` → Panel aktualisiert sich auf Argus-Kontext

## Open Questions

1. **Auto-Trigger aggressiv oder User-initiated?** → Empfehlung: default auto-trigger für Projekt-Notizen (der ganze Wert steckt im "passiert ohne Nachdenken"). Opt-out in Settings.
2. **Gruppen-Kriterium:** Folder-Prefix ist einfach, aber nicht immer semantisch sinnvoll. `projekttyp`-Frontmatter ist semantisch, aber nicht alle Notizen haben es. → v1: Folder-Prefix als Default, `projekttyp` als alternative Option, "flat" (keine Gruppierung) auch.
3. **Auch auf nicht-Projekt-Notizen aktivierbar?** Ja — aber aktiv nur wenn `projectContextScope: "all-notes"`. Default eng (nur Projekte), User kann aufmachen.
4. **Größe der Kandidaten-Liste:** top_k=30 vielleicht zu viel nach Filterung (nur 5 übrig), zu wenig wenn viel schon verlinkt. → Adaptive: top_k starten bei 30, wenn nach Filter <10 übrig → request top_k=50.

## Out-of-Scope

- **"Warum ist diese Notiz relevant?"-Erklärung** — LLM-Aufgabe, out-of-Scope für Mneme.
- **Inline-Embedding-Vorschau** (Content der verwandten Notiz direkt anzeigen) — Obsidian hat eigenes Embed-Feature, User kann `![[Notiz]]` einfügen.
- **Zeitbasierte Relevance** ("neulich oft zusammen bearbeitet") — braucht Activity-Tracking, späteres Feature.
