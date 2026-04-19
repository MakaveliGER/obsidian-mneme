# 2026-04-19 — Integration Hotfix Sprint

**Trigger:** Codex-Review 2026-04-19 — 6 Contract-Brüche in Plugin↔Backend, 2 Schema-/Doku-Drifts.
**Scope:** Bug-Remediation gegen diagnostizierte Liste. Kein neues Feature.
**Exit Criteria:** Alle P0/P1 behoben, Contract-Test für Gardener-Output, `uv run pytest -q` + `npm test` grün.

## Arbeitsreihenfolge (nach Schmerz, nicht nach Nummer)

### Block A — Plugin-Contract (P0, fix zuerst, weil live sichtbar)

1. **P0-1 Health-Modal Feldnamen**
   - Datei: `obsidian-plugin/src/health-modal.ts`
   - `n.suggestions.length` → `n.suggested_links.length` (line 53)
   - `n.path_a` → `n.note_a.path`, `n.path_b` → `n.note_b.path` (line 72-73)
   - Types in `obsidian-plugin/src/types.ts` mitziehen (falls `HealthReport`-Typen divergieren)
   - Begründung: Gardener-Output ist MCP-Tool-Response, wird von Claude Desktop/Code auch gelesen — Backend-Shape ist kanonisch, Plugin anpassen.

2. **P0-2 Listen als JSON-Array senden**
   - Datei: `obsidian-plugin/src/settings.ts:374, 405`
   - `.join(",")` → `JSON.stringify(...)` bei `hook_matchers` und `health.exclude_patterns`
   - Begründung: `config.py:210` erwartet JSON-Array, silent fail aktuell.

3. **P0-3 Auto-Search-Dropdown nutzt Workflow-Methode**
   - Datei: `obsidian-plugin/src/settings.ts:76-79`
   - Statt `scheduleConfigUpdate("auto_search.mode", value)` → `await this.plugin.client.setAutoSearchMode(value)`
   - Begründung: `setAutoSearchMode()` in `mneme-client.ts:527` existiert und macht die Side-Effects (Hook-Registration etc.), die Direktschreibung in Config überspringt sie.

### Block B — Contract-Test gegen Regression

4. **Contract-Test Gardener ↔ Plugin Shape**
   - Neue Datei: `tests/test_gardener_contract.py` oder Erweiterung von `test_gardener.py`
   - Fixiert die Feldnamen die das Plugin konsumiert: `weakly_linked[].suggested_links`, `near_duplicates[].note_a.path`, `near_duplicates[].note_b.path`, `stale_notes[].days_stale`, `orphan_pages[].path`
   - Begründung: Codex-Kernthese — Integrationspfade sind nicht getestet. Ohne diesen Test kommen Feld-Drifts ungebremst zurück.

### Block C — Backend-Härtung (P1)

5. **P1-1 `Store.open_metadata_only()`**
   - Dateien: `src/mneme/store.py` (neue Classmethod), `src/mneme/cli.py:374, 667`
   - Signatur: `Store.open_metadata_only(db_path: Path) -> Store` — überspringt `chunks_vec`-Creation wenn frische DB
   - CLI-Aufrufer umstellen: `status`, `hook-search`
   - Begründung: `embedding_dim=1` + `IF NOT EXISTS` bakes falsche Vector-Dim in frische DB; nächster `reindex` scheitert mit Dim-Mismatch.

6. **P1-2 MCP Resources initialisieren**
   - Datei: `src/mneme/server.py:574, 586, 598`
   - Jeweils `err = _check_init(); if err: return json.dumps(err)` am Anfang
   - Begründung: Tools rufen `_check_init()`, Resources nicht — stdio-Cold-Start bricht bei Resource-Read vor erstem Tool-Call.

7. **P1-3 `stale_notes` fachlich korrekt: `indexed_at` + `modified_at` trennen**
   - Dateien: `src/mneme/store.py` (Schema-Migration), `src/mneme/gardener.py:169`
   - Schema: neues Feld `modified_at` (fs-mtime), `updated_at` in `indexed_at` umbenennen
   - Migration: bestehende DBs — `ALTER TABLE notes ADD COLUMN modified_at TEXT`, Backfill aus `updated_at`
   - Indexer: `modified_at = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat()`
   - Gardener: liest `modified_at` statt `updated_at`
   - **Risiko:** Schema-Change. Falls zu groß für diesen Sprint — splitten in eigenes v0.3.2-Ticket und nur Doku hinzufügen ("stale_notes misst Re-Index-Zeit, nicht File-Änderung").

### Block D — P2 Cleanup

8. **P2-1 `near_duplicates` Determinismus**
   - Datei: `src/mneme/gardener.py:219`
   - `random.sample(..., 30)` → `random.Random(seed=len(all_paths)).sample(..., 30)` ODER kompletter Scan + N² Vergleich (wenn Vault < 500 Notes)
   - Begründung: Nondeterministisch + im UI nicht transparent.

9. **P2-2 `autoStartServer` Doku/Default-Alignment**
   - Datei: `obsidian-plugin/src/settings.ts:416` und/oder `obsidian-plugin/src/types.ts:70`
   - Entscheiden: Default `true` (Code) ist richtig → Doku anpassen. Oder Default `false` (Doku) → Code anpassen.
   - Gleiches für `keepServerRunningAfterClose` + `main.ts:183`-Kommentar
   - Begründung: Drei widersprüchliche Aussagen zum gleichen Flag — leichter Doc-Fix.

## Validierung

- `uv run --with pytest pytest -q` (erwartet: alle neuen Contract-Tests passed, keine Regression in 320 bestehenden)
- `npm test` im Plugin (26 Tests)
- Manueller Live-Test:
  - Plugin Health-Modal klicken → alle 4 Sektionen rendern ohne `undefined`
  - Settings: Auto-Search-Dropdown ändern → Notice bestätigt Workflow
  - Settings: hookMatchers ändern → Backend übernimmt Wert (Check via `mneme get-config`)
  - `mneme status` auf leerer DB → kein Dim-Lock

## Out-of-Scope (explizit)

- Feature-Arbeit aus `Featureideen.md` — kommt nach diesem Sprint
- God-Module-Split (`server.py` 860 LOC etc.) — architektonisch, eigenes Refactor-Ticket
- `--json default=True`-Flag-Cleanup in CLI — kosmetisch, niedrige Prio

## Release-Plan

Nach Abschluss: v0.3.2 bundeln (nicht pushen). Feature-Arbeit folgt, gemeinsam als v0.4 releasen.
