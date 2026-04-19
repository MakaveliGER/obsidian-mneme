# Spec — Auto-Link on Create

**Block:** 2 (Daily-PKM-Power)
**Aufwand:** M (~1 Tag)
**Status:** draft

## Problem

Notizen werden angelegt ohne Verknüpfung zu bestehendem Wissen. Wikilinks entstehen rein manuell und werden oft vergessen — mit der Folge, dass neue Notizen im Vault **isoliert** liegen und Querverbindungen nie gebaut werden. Der Vault-Wert entsteht durch Vernetzung, nicht durch Masse. Jede unverlinkte Notiz ist verschenkter Vault-Wert.

Verwandt mit Duplikat-Warnung: **gleicher Moment (neue Notiz), anderer Zweck** — Duplikat-Warnung sagt "gibt's schon", Auto-Link sagt "hänge sie hier rein".

## User Story

> Wenn ich eine neue Notiz anlege und ein paar Zeilen Content geschrieben habe, öffne ich per Command-Palette oder Button `Mneme: Vorschläge für Wikilinks`. Mneme zeigt mir eine Liste von **5-10 semantisch passenden** bestehenden Notizen. Ich akzeptiere Vorschläge einzeln per Klick — jeder Klick fügt `[[...]]` an einer sinnvollen Stelle ein (End der Notiz, Section "Siehe auch").

## Lösung

### Trigger
**Nicht automatisch** beim Create (zu aufdringlich beim Schreibfluss). Stattdessen:
- Plugin-Command: `Mneme: Link-Vorschläge für aktive Notiz`
- Plugin-Ribbon-Icon (optional)
- Oder: automatischer Reminder als Notice wenn Notiz nach 5 Min noch 0 Wikilinks hat

### Flow
1. User triggert Command auf aktiver Notiz.
2. Plugin sendet Notiz-Path + Content an `POST /api/v1/link-suggestions`.
3. Backend: Embedding berechnen, top-K ähnliche Notizen, exkludiert die aktive Notiz und bereits verlinkte Notizen.
4. Plugin zeigt Sidebar-Panel oder Modal mit Vorschlägen, jeweils: `[Titel] · [%] · [Snippet]`.
5. Click auf Vorschlag → fügt `[[Pfad|Titel]]` an einer konfigurierbaren Position ein.

### Einfüge-Position (konfigurierbar)
- **"Siehe auch"-Sektion am Ende** (default): fügt bei Bedarf Header `## Siehe auch` hinzu, darunter Bullet-Liste
- **Frontmatter-Property** `related: [[x]], [[y]]`
- **Inline am Cursor** (rein manuell, User entscheidet Position)

## Interface

### REST-Endpoint

```
POST /api/v1/link-suggestions
{
  "path": "02 Projekte/Neue-Notiz.md",
  "content": "Voller Body der Notiz",
  "exclude_linked": true,
  "top_k": 10,
  "min_similarity": 0.5
}
```

Response:
```json
{
  "suggestions": [
    {
      "path": "02 Projekte/RAG-Eval.md",
      "title": "RAG-Eval",
      "similarity": 0.82,
      "relevance_pct": 100,
      "content": "Snippet..."
    }
  ],
  "already_linked": ["04 Ressourcen/..."],
  "total_candidates": 10
}
```

### MCP-Tool (für Claudian-Use)

```python
def suggest_links(path: str, top_k: int = 10) -> dict
```

### Plugin-Command

```ts
// src/commands/suggest-links.ts
this.addCommand({
  id: "mneme-suggest-links",
  name: "Link-Vorschläge für aktive Notiz",
  editorCallback: (editor, view) => { ... }
});
```

### Plugin-Settings
- `autoLinkInsertMode: "section" | "frontmatter" | "cursor"` (default `"section"`)
- `autoLinkSectionName: string` (default `"Siehe auch"`)
- `autoLinkMinSimilarity: number` (default 0.5)
- `autoLinkReminderEnabled: boolean` (default false) — Notice wenn Notiz 5 min alt ohne Links

## Daten

Keine Schema-Änderung. Nutzt bestehende Wikilink-Tabelle um `already_linked`-Set zu bauen.

## Abhängigkeiten

- **Nicht blockierend** aber **Synergie** mit Duplikat-Warnung: beide triggern am "neue Notiz"-Moment. Könnten im Plugin gemeinsam konfiguriert werden.
- Health-Report Stufe 2 "Weakly Linked expand" nutzt denselben Backend-Endpoint → Code-Sharing.

## Test Plan

### Backend
- `test_link_suggestions_excludes_already_linked`: bestehende Wikilinks werden rausgefiltert
- `test_link_suggestions_excludes_self`: aktive Notiz nie in Vorschlägen
- `test_link_suggestions_respects_min_similarity`: Threshold-Filtering
- `test_link_suggestions_deterministic`: gleicher Content → gleiche Top-K-Reihenfolge

### Plugin
- Mock-Suggestions → Modal rendert, Click fügt Link ein an richtiger Stelle
- "Siehe auch"-Section wird angelegt wenn nicht vorhanden, erweitert wenn da
- Frontmatter-Mode fügt `related: []`-Array korrekt ein

### Live-Akzeptanz
- Neue Notiz mit 5 Zeilen Content zu bekanntem Thema → Command liefert sinnvolle Top-5 → nach Klick Link ist da

## Open Questions

1. **Insert-UX:** Click = Insert, oder Click = Preview + expliziter "Einfügen"-Button? → Empfehlung: Click = direkter Insert mit Undo-Hinweis.
2. **Bulk-Insert:** "Alle Top-5 einfügen" Button? → Empfehlung: ja, als sekundäre Aktion.
3. **Notice bei unverlinktem Neu-Stand:** nervig oder hilfreich? → default off, Opt-in via Setting.
4. **Link-Text-Darstellung:** `[[Pfad]]` oder `[[Pfad|Titel]]` (Alias)? → Empfehlung: Alias wenn Pfad lang oder Folder-Prefix hat.

## Out-of-Scope

- **Bidirektionale Links:** Auto-Link fügt nur in Richtung neue→alte Notiz. Rückrichtung wäre Vault-Write auf zweite Datei — höheres Risiko, Parken für Stufe-3-Vault-Write-Block.
- **LLM-basierte Link-Platzierung** (NLP analysiert wo Link im Text am besten passt): interessant aber explizit rausgelassen. "Siehe auch"-Pattern ist PKM-Standard.
