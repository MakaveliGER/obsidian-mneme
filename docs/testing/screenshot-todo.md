# Screenshot TODO — Obsidian Mneme v0.3.1

README und GitHub-Release-Page zeigen aktuell Platzhalter-PNGs in
Mneme-Brand-Farben. Die echten Screenshots fehlen noch.

**Generiert durch:** `scripts/make_screenshot_placeholders.py` (einmalig
ausführen reicht — Resultate werden unter `design/screenshots/` in Git
gehalten, damit GitHub keine kaputten Image-Icons zeigt).

## Was abzufotografieren ist

### 1. `design/screenshots/plugin-search.png`

**Motiv:** Plugin-Such-Sidebar mit Ergebnissen — zeigt semantische
Hybrid-Suche in Aktion.

**Setup:**
- Obsidian öffnen, Mneme-Plugin aktiv, Server läuft (Toast
  "HTTP-Fast-Path aktiv (Port 8765)" erschien beim Start).
- Ribbon-Icon (goldene Muse) klicken → Sidebar öffnet sich.
- Query tippen: z.B. `RAG`, `Prompt Engineering`, `Semantic Search`.
- Suchen-Button drücken, Ergebnisse mit bunten %-Badges erscheinen.

**Was im Frame sein soll:**
- Suchfeld mit Query
- 5-8 Ergebnisse sichtbar mit Titel + Pfad + Snippet + %-Badge
- Minimum ein grünes, ein gelbes, ein rotes Badge (zeigt Relevanz-Abstufung)

**Format:** PNG, ~800-1200px breit.

### 2. `design/screenshots/claudian-toolcall.png`

**Motiv:** Claude Desktop nutzt `search_notes` automatisch.

**Setup:**
- Claude Desktop öffnen, neuer Chat.
- Prompt: *"Fass mir zusammen was ich über RAG-Evaluierung in meinem Vault
  notiert habe"* (oder ähnliche persönliche Frage).
- Claude ruft `search_notes` → Tool-Call-Widget klappt auf.
- Screenshot, sobald Tool-Call UND Antwort-Beginn sichtbar sind.

**Was im Frame sein soll:**
- User-Prompt oben
- Tool-Call-Widget expanded ("Using tool: `search_notes`…" oder ähnlich)
- Antwort-Anfang unten, der die Vault-Inhalte referenziert

**Format:** PNG, ~900-1200px breit.

### 3. `design/screenshots/plugin-health.png`

**Motiv:** Vault-Health-Modal im Obsidian-Plugin.

**Setup:**
- Command Palette (Ctrl/Cmd+P) → "Mneme: Vault-Health".
- Modal öffnet sich, zeigt mehrere Sektionen (Orphans, Weak Links, Stale,
  Duplicates).
- Mindestens zwei Sektionen ausgeklappt mit Inhalt.

**Was im Frame sein soll:**
- Modal-Überschrift
- Zwei sichtbare Sektionen mit mindestens je 2-3 Einträgen
- Keine sensiblen Notiz-Pfade oder -Titel (Vault vorher anonymisieren oder
  kleine Test-Vault nehmen falls die Namen sensibel sind)

**Format:** PNG, ~800-1200px breit.

## Nach dem Abfotografieren

1. Dateien mit **exakt** den obigen Namen speichern (kleingeschrieben, mit
   Bindestrichen, `.png`-Endung).
2. `git add design/screenshots/` und committen.
3. `README.md` kontrollieren — die drei Image-Markdown-Referenzen greifen
   automatisch auf die neuen Dateien zu.

## Placeholder regenerieren

Falls die Placeholder mal verloren gehen oder angepasst werden sollen:

```bash
uv tool run --with pillow python scripts/make_screenshot_placeholders.py
```
