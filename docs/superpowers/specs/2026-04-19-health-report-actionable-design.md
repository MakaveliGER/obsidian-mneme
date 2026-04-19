# Spec — Health-Report actionable Stufe 1+2

**Block:** 1 (Schnellwins) — Live-Test-getrieben
**Aufwand:** S-M (4-8h)
**Status:** draft

## Problem

Live-Test 2026-04-19: Das Health-Modal zeigt Zahlen (`26 Orphans, 10 Weakly Linked, 0 Stale, 0 Duplicates`) aber **erklärt nichts und bietet keine Aktion**. User-Zitat sinngemäß: "Was mach ich jetzt damit?"

Konkret fehlt:
1. **Kontext** — was bedeutet "Orphan"? Ist 26/150 viel oder wenig?
2. **Navigation** — bei Weakly Linked werden 3 Link-Vorschläge **schon im Backend berechnet**, das Modal ignoriert sie. Nur Count wird angezeigt.
3. **Drift-Signal** — Temporal Drift (alte Notizen driften semantisch von neueren weg) als zusätzlicher Health-Check fehlt noch.

## User Story (Stufe 1+2 — kein Vault-Write)

> Ich öffne `Mneme: Vault health check`. Modal zeigt mir:
> - Pro Sektion **1 Satz Erklärung** + Faustregel
> - **Kontext-Zahlen:** "26 von 150 (17%) — bei <30% OK"
> - Bei Weakly Linked: Click auf Item **expandet** → zeigt die 3 Link-Vorschläge, ich kann zur Vorschlag-Notiz navigieren
> - **Neue Sektion Temporal Drift** — Notizen älter als X, semantisch driftend, mit Hinweis worin die Drift besteht
> - **Empty-States** mit Sinn: "0 Duplikate → ✓ sauber"

## Lösung

### Stufe 1 — Verständnis (frontend-only, kein Backend-Change)

**Statische Texte im Plugin:**

```ts
const SECTION_DESCRIPTIONS = {
  orphan_pages: {
    short: "Notizen ohne eingehende Wikilinks.",
    action: "Nicht per se schlecht — aber problematisch wenn Kern-Wissen isoliert bleibt.",
    threshold_hint: (count, total) => count / total > 0.3 ? "⚠️ Hoch" : "✓ OK",
  },
  weakly_linked: {
    short: "Notizen mit ≤1 Link und semantisch nahen Nachbarn.",
    action: "Ideale Kandidaten für schnelle Verlinkung — Click auf Item zeigt Vorschläge.",
    threshold_hint: () => null,
  },
  stale_notes: {
    short: "Aktive Notizen die seit >30 Tagen nicht bearbeitet wurden.",
    action: "Review ob noch aktuell. Evtl. Status ändern oder Inhalt updaten.",
    threshold_hint: () => null,
  },
  near_duplicates: {
    short: "Notizen-Paare mit >85% semantischer Ähnlichkeit.",
    action: "Review ob Merge sinnvoll oder Begriffstrennung nötig.",
    threshold_hint: (count) => count === 0 ? "✓ sauber" : null,
  },
  temporal_drift: {
    short: "Alte Notizen die semantisch von neueren zum selben Thema abweichen.",
    action: "Oft Zeichen veralteter Infos (Modell-Versionen, APIs, Preise).",
    threshold_hint: () => null,
  },
};
```

**Empty-State pro Sektion:** Wenn Count = 0, Sektion-Header grün + Text "✓ [Positiv-Framing]".

**Header-Format neu:**
```
Orphan Pages              26 / 150 (17%)  ✓ OK
─────────────────────────────────────────────
Notizen ohne eingehende Wikilinks. Nicht per se schlecht — aber
problematisch wenn Kern-Wissen isoliert bleibt.
[expand ▼]
```

### Stufe 2 — Navigation (frontend + kleiner backend-extend)

**Weakly Linked Expand-UX:**
- Click auf Item toggled inline-Details
- Details zeigen die 3 `suggested_links` (schon im Backend-Response, bisher ignoriert)
- Jedes Suggestion-Item: `[Titel] · [Similarity %]` · Click → öffnet Vorschlag-Notiz in neuer Pane
- Plus: Button "Als Link in diese Notiz einfügen" → **öffnet** die aktuelle Notiz mit Cursor an "Siehe auch"-Section (kein Auto-Write in v1)

**Near-Duplicates Diff-UX (optional in v1):**
- Click auf Duplicate-Paar → öffnet beide Notizen in Side-by-Side-Panes (Obsidian-Standard-Split)
- Kein echter Diff-Viewer (wäre Vault-Write-Kandidat)

**Temporal Drift (neue Sektion):**
- Backend-Extend: neue Methode `find_drifted_notes(threshold: float = 0.3)` in Gardener
- Algorithmus: für jede Notiz älter als 180 Tage: hole top-10 semantische Nachbarn → berechne Mittelwert der Ähnlichkeiten zum Cluster-Zentrum → wenn deutlich niedriger als Cluster-Durchschnitt → drifted
- Pro gedrifteter Notiz: Pfad, days_old, drift_score, 2-3 Vergleichsnotizen

### Performance

`find_weakly_linked` ist langsam (2026-04-19 Live-Test: ~10s auf 150 Notizen auf CPU). Teil-Fix:
- Batch-Embedding-Berechnung: statt pro Kandidat eigenen `get_similar`-Call, einmal alle Kandidaten-Embeddings holen, dann parallele Ähnlichkeit
- Ziel: <3s auf CPU

## Interface

### Backend (Gardener-Extension)

```python
class VaultGardener:
    def find_drifted_notes(
        self,
        older_than_days: int = 180,
        drift_threshold: float = 0.3,
        top_k: int = 10,
    ) -> list[dict]:
        """Find notes semantically drifted from their neighbors.

        Returns list of {path, title, days_old, drift_score,
                         compared_against: [{path, similarity}]}.
        """
```

`full_report()` ergänzt um key `"drifted_notes"` — zusätzlich in `VaultHealthReport`-TypedDict.

Kein neues MCP-Tool — `vault_health` bekommt neuen optionalen Check-Typ `"drift"` im `checks`-Parameter:
```python
def vault_health(checks: list[str] = None, ...) -> dict:
    # valid check names: orphans, weakly_linked, stale, duplicates, drift
```

### Plugin

- `health-modal.ts` erweitert:
  - Section-Description-Konstante (siehe oben)
  - Expand-UX für Weakly Linked + Near Duplicates
  - Neue Sektion "Temporal Drift"
- `types.ts` HealthReport erweitert um `drifted_notes`
- Neuer Contract-Test: Feld `drift_score` und `compared_against` backend-pinned

### Keine Flag-Änderung

`vault_health` akzeptiert schon beliebige `checks`-Liste → `"drift"` ist ein add-only.

## Daten

Keine Schema-Änderung. Nutzt vorhandene Embeddings + modified_at.

## Abhängigkeiten

- **Keine harten** Feature-Abhängigkeiten. 
- **Synergie mit Schema v3 (`modified_at`)** — gerade implementiert, Drift-Check nutzt es als Age-Indikator.

## Test Plan

### Backend
- `test_find_drifted_notes_old_outlier`: alte Notiz mit Embedding weit weg von neuen Nachbarn → in Ergebnis
- `test_find_drifted_notes_young_excluded`: junge Notizen unter `older_than_days` → nie drifted
- `test_find_drifted_notes_no_neighbors`: isolierte Notiz ohne Topic-Nachbarn → nicht drifted (kann nicht driften gegen nichts)
- `test_find_drifted_notes_respects_exclude_patterns`
- `test_vault_health_check_drift`: neuer Check-Typ routed auf find_drifted_notes
- **Performance-Test** für weakly_linked: mit 150 Dummy-Notizen < 3s (neu, falls Batch-Optimierung)

### Plugin
- Mock-Response mit drifted_notes → Sektion rendert
- Description-Texte sind in allen Sections vorhanden
- Weakly Linked: Click auf Item zeigt suggested_links
- Empty-State: `{..., near_duplicates: []}` → grüner Haken + Positiv-Text
- Kontext-Zahlen: `26 / 150 (17%)` im Header sichtbar
- Contract-Test extended um Drift-Shape

### Live-Akzeptanz
- Modal öffnet, User versteht auf den ersten Blick was jede Sektion bedeutet
- Weakly Linked expandiert, Navigation zur Vorschlag-Notiz funktioniert
- Temporal Drift zeigt bei altem Vault sinnvolle Treffer (oder "keine Drift gefunden" wenn Vault noch jung)
- Laufzeit akzeptabel (<5s)

## Open Questions

1. **Temporal-Drift-Threshold:** 0.3 relative Abweichung ist Schätzung. → Offen für Kalibrierung nach ersten Live-Runs. Anfangs restriktiv, dann öffnen.
2. **Drift-Explanation:** "Drift-Score: 0.42" sagt dem User wenig. → Empfehlung: drift_score + drift_label ("leicht" / "mittel" / "stark") basierend auf Buckets.
3. **Kontext-Zahlen-Berechnung:** Für Orphans `count/total` — `total` = alle Notizen oder nur aktive? → Empfehlung: alle Notizen exkl. exclude_patterns.
4. **Batch-Embedding für weakly_linked:** größere Refactor als der Rest. Separat oder mit? → Empfehlung: mit. Sonst bleibt UX-Fix hinter "immer-noch-langsam"-Feedback zurück.

## Out-of-Scope (→ Stufe 3)

- Vault-Write-Aktionen: Link einfügen, Stale archivieren, Duplicates mergen — alle separate Stufe-3-Features
- **LLM-basierte Erklärung** "warum ist X stale?" — Claudian-Aufgabe
- **Dashboard-Ansicht** im Plugin (persistente Tabelle statt Modal) — out-of-scope, Modal-UX reicht für v1
