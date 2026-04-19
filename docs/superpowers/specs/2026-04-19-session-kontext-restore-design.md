# Spec — Session-Kontext-Restore

**Block:** 2 (Daily-PKM-Power)
**Aufwand:** M (~1 Tag)
**Status:** draft

## Problem

Frage "Wo war ich bei Projekt X stehengeblieben?" — klassischer PKM-Pain-Point nach Pause (Wochenende, Urlaub, Kontextwechsel). Informationen sind im Vault verstreut:
- Letztes Edit-Datum in Projekt-Notiz
- Offene Tasks in `01 Inbox/Tasks.md`
- Relevante Daily-Notes-Einträge der letzten Tage
- Aktuell aktiver Status im Frontmatter
- Kürzliche Commits (falls Projekt = Code)

Manuelles Zusammensuchen dauert 10 Min pro Projekt, wird deshalb oft übersprungen, Kontext-Reaktivierung leidet.

## User Story

> Ich öffne am Montag Claude / Claudian und frage `Mneme, wo war ich bei Mneme?` (oder via Plugin-Command `Mneme: Kontext für aktive Notiz`). Ich bekomme einen kompakten Block:
> - **Letzter Stand:** "Commit `7c36113` am 2026-04-19 — Codex-Review-Abschluss" (wenn Projekt hat git-Info)
> - **Letzte 3 Daily-Note-Einträge** die das Projekt erwähnen
> - **Offene Tasks** zum Projekt
> - **Status aus Frontmatter:** aktiv, nächste Schritte: X, Y
> - **5 zuletzt editierte Notizen im Projekt-Ordner**

## Lösung

### Trigger-Varianten
1. MCP-Tool `restore_session_context(project_or_topic)` — von Claude aufrufbar
2. Plugin-Command "Kontext für aktive Notiz" — nutzt aktiven Pfad als Projekt-Indikator
3. CLI `mneme context "Mneme"` (selten, aber konsistent)

### Inputs
- **Projekt-Name** (String) oder **Ordner-Pfad** oder **Notiz-Pfad** — Mneme muss aus diesem Signal den "Projekt-Scope" ableiten

### Scope-Resolution
```
Input "Mneme" (String):
  → search_notes(query="Mneme", top_k=1) → path "02 Projekte/Eigenprojekte/Mneme/Mneme.md"
  → Scope = Parent-Folder "02 Projekte/Eigenprojekte/Mneme/"

Input "02 Projekte/Eigenprojekte/Mneme/Mneme.md":
  → Direkt: Scope = Parent-Folder

Input Active Note (Plugin):
  → Notiz-Pfad → Parent-Folder
```

### Datenquellen
1. **Projekt-Notiz-Frontmatter:** `status`, `nächste Schritte`, `projekttyp`, `repo`
2. **Ordner-Inhalte:** letzten 5 modifizierten `.md` unter Scope-Folder
3. **Daily-Notes-Scan:** letzten N Daily-Notes (default 14 Tage), volltext-suche nach Projekt-Titel + Wikilink-Text. Backlink wäre präziser aber langsamer — für v1 FTS5-Match.
4. **Tasks-Scan:** `01 Inbox/Tasks.md` (oder konfigurierbarer Pfad) — Zeilen mit `- [ ]` die das Projekt erwähnen
5. **Git-Info (optional):** wenn Frontmatter `repo` oder `lokaler-pfad` hat UND Pfad lokal existiert → `git log -1` Meta. Out-of-scope für v1 wenn zu komplex; hinterlassen als hook.

### Output-Format
Strukturiertes JSON — Claude rendert das gut, Plugin kann in Sidebar-Panel darstellen.

## Interface

### MCP-Tool

```python
def restore_session_context(
    project_or_topic: str,
    daily_notes_days: int = 14,
    top_recent_files: int = 5,
) -> dict
```

Response:
```json
{
  "project": {
    "name": "Mneme",
    "primary_note": "02 Projekte/Eigenprojekte/Mneme/Mneme.md",
    "folder": "02 Projekte/Eigenprojekte/Mneme/",
    "confidence": 0.92
  },
  "status_from_frontmatter": {
    "status": "aktiv",
    "projekttyp": "code",
    "other_props": {...}
  },
  "recent_files_in_scope": [
    {"path": "...", "title": "...", "modified_at": "..."}
  ],
  "daily_note_mentions": [
    {
      "daily_note_path": "05 Daily Notes/2026/2026-04/2026-04-19.md",
      "date": "2026-04-19",
      "excerpt": "Session 4 — Mneme v0.3.1 Retrieval-UX Round 3..."
    }
  ],
  "open_tasks": [
    {"file": "01 Inbox/Tasks.md", "line": 45, "text": "- [ ] ..."}
  ],
  "next_steps_from_frontmatter": "..." ,
  "git_last_commit": null
}
```

### REST + CLI
- `POST /api/v1/session-context`
- `mneme context <project_or_topic>`

### Plugin
- Neuer Command "Mneme: Kontext für aktive Notiz"
- Sidebar-Panel zeigt formatiert (Sektion pro Datenquelle, Click-to-Open überall)

## Daten

Keine Schema-Änderung.

- FTS5 für Daily-Note-Mentions (bereits da)
- Frontmatter wird beim Index gespeichert — Reader über bestehende `Store.get_note_by_path()`

## Abhängigkeiten

- **Tasks-Pfad hardcoded `01 Inbox/Tasks.md`** — sollte konfigurierbar in `config.tasks.path`. Neuer Config-Eintrag. Keine Schema-Änderung, nur TOML-Key.
- Keine Feature-Abhängigkeiten.

## Test Plan

### Backend
- `test_restore_context_resolves_string_to_project`: "Mneme" → findet Projekt-Notiz
- `test_restore_context_resolves_direct_path`: Pfad direkt übergeben → Scope = Parent
- `test_restore_context_reads_frontmatter`: status, projekttyp aus FM extrahiert
- `test_restore_context_daily_notes_mentions`: Daily-Notes-Scan findet Erwähnungen
- `test_restore_context_open_tasks_filtered_by_project`: Tasks werden nach Projekt-String gefiltert
- `test_restore_context_honors_exclude_patterns`: Archiv etc. wird nicht gescannt

### Plugin
- Mock-Response → Panel rendert alle Sektionen
- Leere Sektionen werden elegant unterdrückt (z.B. 0 Tasks → Sektion ausblenden)

### Live-Akzeptanz
- Input `"Mneme"` → Output enthält unsere echten Daily-Note-Sessions, Status `aktiv`, "nächste Schritte" aus Mneme.md
- Input `"Hohenstein"` → Output enthält Hohenstein-Bereich-Notizen + Daily-Mentions

## Open Questions

1. **Scope-Ambiguität:** "Mneme" matcht evtl. Projekt-Notiz UND andere. Welchen Match nehmen? → Empfehlung: top-1, aber `confidence`-Score mitgeben. Plugin kann "andere Optionen" Button zeigen wenn <0.8.
2. **Daily-Note-Mentions via FTS5 oder Backlinks?** → FTS5 ist einfacher, Backlinks präziser. v1: FTS5. v2: beides mergen.
3. **Git-Info einbauen:** braucht subprocess-Call, bricht bei fehlendem git. → v1 rauslassen, als klarer Extension-Point im Code markieren.
4. **Tasks.md-Parsing:** Format-robust? (Obsidian-Checkboxen, Dataview-Queries, Nested). → v1: nur simple `- [ ]` Zeilen mit Text-Match. Robustere Tasks-Plugin-Integration → v2.

## Out-of-Scope

- **Aktive Zeit-Tracking** ("du warst heute 2h an X dran") — braucht Editor-Telemetrie, zu aufdringlich
- **Predictive:** "du solltest jetzt X machen" — zu weit Richtung LLM-Reasoning, Claudian's Job
- **Auto-Open** der Projekt-Dateien — Plugin könnte Buttons haben, aber Mneme entscheidet nie autonom
