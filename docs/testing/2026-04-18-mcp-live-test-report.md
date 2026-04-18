# MCP Live-Test Report — Mneme v0.3.1

**Datum:** 2026-04-18
**Version:** obsidian-mneme v0.3.1 (pre-release)
**Vault:** 177 Notizen, 1526 Chunks, 20.21 MB
**Embedding-Modell:** BAAI/bge-m3
**Hardware:** AMD RX 7900 XTX (ROCm), Python 3.12
**Transport:** streamable-http
**Tester:** Claudian (Claude) via MCP-Tool-Calls + paralleler Source-Code-Review

---

## Executive Summary

Mneme v0.3.1 ist **nicht release-fähig in aktuellem Zustand**. Ein kritischer Bug macht `get_note_context.similar_notes` für große Notizen vollständig nutzlos — betroffen sind genau die Notizen, für die Kontext-Navigation am wertvollsten wäre (Projekt-Hauptdateien, MOCs). Der Fix ist bekannt und klein.

Die semantische Kernfunktion (`search_notes`) arbeitet **korrekt und schnell** — Deutsch-natürlichsprachliche Queries, Filter-Kombinationen und Performance sind produktionsreif. MCP-Transport ohne Probleme.

**Release-Empfehlung:** v0.3.1 nach Fix von BUG 1 (und optional BUG 2) releasen. BUG 1 ist ein 1-Zeilen-Fix.

| Kategorie | Status |
|---|---|
| `search_notes` — Semantik + Filter | ✅ Produktionsreif |
| `get_note_context` — Graph-Nachbarn | ✅ Korrekt |
| `get_note_context` — similar_notes (große Notizen) | ❌ Kritischer Bug |
| `get_similar` (MCP-Tool direkt, kleine Notizen) | ⚠️ Degradiert |
| `vault_health` — Orphan Detection | ✅ Korrekt |
| `vault_health` — weak_links Vorschläge | ⚠️ Minor Bug (Duplikate) |
| MCP-Transport (streamable-http) | ✅ Stabil |
| Performance | ✅ Produktionsreif |

---

## Bugs

### BUG 1 — Kritisch: `get_similar` Over-Retrieval zu klein → `get_note_context.similar_notes` immer leer

**Schweregrad:** Kritisch — Feature für große Notizen komplett defekt

**Root Cause:**

In `search.py`, Zeile 214:

```python
candidates = self.store.vector_search(avg_embedding, top_k=top_k * 3)
filtered = [r for r in candidates if r.note_path != path]
return filtered[:top_k]
```

Der Over-Retrieval-Faktor `top_k * 3` ist zu klein für Notizen mit vielen Chunks. Bei Mneme.md (~350 Zeilen, N Chunks) und Argus.md (ähnlich groß) belegen die eigenen Chunks alle `top_k * 3` Slots im Vector-Search-Ergebnis. Nach dem Path-Filter bleibt nichts übrig.

**Reproduktion:**

```
# Intern via get_note_context (similar_k=3 → vector_search(top_k=9)):
get_note_context("02 Projekte/Eigenprojekte/Mneme/Mneme.md", similar_k=3)
→ similar_notes: []   # alle 9 Kandidaten = Mneme.md-Chunks

get_note_context("02 Projekte/Eigenprojekte/Argus/Argus.md", similar_k=3)
→ similar_notes: []   # alle 9 Kandidaten = Argus.md-Chunks

# MCP-Tool direkt (top_k=5 → vector_search(top_k=15)):
get_similar("02 Projekte/Eigenprojekte/Argus/Argus.md", top_k=5)
→ total_results: 0    # alle 15 Kandidaten = Argus.md-Chunks

get_similar("02 Projekte/Eigenprojekte/Mneme/Mneme.md", top_k=5)
→ total_results: 1    # 14 Mneme.md + 1 Fremder (Mneme-Recherche.md, Score: 0.4874)
```

**Betroffene Methoden:** `SearchEngine.get_similar()`, indirekt `get_note_context` (MCP-Tool)

**Fix-Vorschlag:**

Option A — Schnellfix (robust, 1 Zeile):
```python
candidates = self.store.vector_search(avg_embedding, top_k=top_k * 10 + 20)
```

Option B — Präziser Fix (optimal):
```python
n_own_chunks = len(embeddings)  # bereits berechnet im gleichen scope
candidates = self.store.vector_search(avg_embedding, top_k=n_own_chunks + top_k + 10)
```
Option B nutzt die im selben Scope bereits vorhandene `embeddings`-Variable — kein extra DB-Query, kein Performance-Overhead.

---

### BUG 2 — Minor: `vault_health` weak_links — Duplikat-Vorschläge pro Notiz

**Schweregrad:** Minor — UX-Problem, keine Datenverlust/Funktionsausfall

**Root Cause:**

`gardener.find_weakly_linked()` dedupliziert `suggested_links` nicht auf Note-Ebene. Verschiedene Chunks einer Notiz landen als separate Einträge.

**Reproduktion:**

```
vault_health(checks=["weak_links"])
→ "UI-UX Pro Max — KI-gestütztes Design System":
   suggested_links: [
     {path: "Claude Skills Recherche...", score: 0.72},  # Chunk 1
     {path: "Claude Skills Recherche...", score: 0.69},  # Chunk 2
     {path: "Claude Skills Recherche...", score: 0.67},  # Chunk 3
   ]
```

Gleiche Notiz dreimal als Vorschlag — redundant, rauscht den Output auf.

**Fix-Vorschlag:**

In `gardener.py`, `find_weakly_linked()` — nach Note-Pfad deduplizieren, besten Score pro Notiz behalten:

```python
seen_paths = {}
for result in candidates:
    if result.note_path not in seen_paths or result.score > seen_paths[result.note_path]:
        seen_paths[result.note_path] = result.score
suggested_links = [{"path": p, "score": s} for p, s in seen_paths.items()]
```

---

## Observations

### OBS 1 — `get_similar` MCP-Tool: fehlende Felder gegenüber REST API

Das MCP-Tool `get_similar` gibt `{path, title, score}` zurück — die REST API `/api/v1/similar` gibt zusätzlich `heading_path`, `content`, `tags`. Ohne `heading_path` und `content` ist für den LLM-Client nicht erkennbar, **welcher Teil** der ähnlichen Notiz inhaltlich relevant ist — ein zusätzlicher `get_note_context`-Call wird nötig.

**Verbesserungsvorschlag:** Optionalen Parameter `include_content: bool = False` ergänzen. Default `False` hält Response klein; mit `True` gibt der Client sofort verwertbaren Kontext.

### OBS 2 — Kein Minimum-Score-Threshold / Relevanzschutz

`search_notes` gibt immer `top_k` Ergebnisse zurück, unabhängig von der Query-Qualität. Getestet:

```
search_notes("wat")  # Nonsens, 3 Zeichen
→ Scores: 0.0098, 0.0097, 0.0095

search_notes("KI-Weiterbildung Hohenstein Akademie")  # sinnvolle Query
→ Scores: 0.0098, ...
```

Für LLM-Clients ist das irreführend — die Ergebnisse wirken gleich relevant. Mneme kann nicht signalisieren "diese Query hat keinen Vault-Content getroffen".

**Verbesserungsvorschlag:** `min_score` Parameter (default `None`) oder `low_confidence: true` Flag im Response wenn alle Scores unter einem Threshold (Richtwert: RRF < 0.005) liegen.

### OBS 3 — Multi-Chunk-Flooding bei Single-Note-Dominanz

Bei Queries wie "Wie lege ich ein neues Projekt an?" landen 4 von 5 Ergebnissen als verschiedene Heading-Sections aus `Projekt-Workflow.md`. Bei "Python ROCm GPU Embedding" kommen 3 von 5 aus `Mneme.md`.

Technisch korrekt (die Chunks sind relevant), aber bei `top_k=5` dominiert eine Notiz den gesamten Output. Für reine Notiz-Discovery suboptimal.

**Verbesserungsvorschlag (optional):** `max_per_note: int = None` Parameter. Kein Breaking Change — Default `None` = aktuelles Verhalten bleibt erhalten.

---

## What Works

### Semantische Suche — Deutsch-natürlichsprachlich

Alle getesteten Queries haben die korrekte Notiz auf Position 1 geliefert:

| Query | Erwartete Notiz | Ergebnis |
|---|---|---|
| "Wie erkenne ich ein Setup im Chart?" | KITS research (Chart-Setup-Logik) | ✅ |
| "Wie lege ich ein neues Projekt an?" | Projekt-Workflow.md | ✅ |
| "Pipe-Buffer Blockade stdio Prozess hängt" | Mneme MCP-Hang-Entscheidung | ✅ |

### Filter-Kombinationen

```
folders=["03 Bereiche", "02 Projekte"]  →  korrekt gefiltert  ✅
tags=["code", "ki"]                     →  korrekt gefiltert  ✅
after="2026-04-15"                      →  korrekt gefiltert  ✅
```

### Performance

| Szenario | Latenz |
|---|---|
| Cold (nach Model-Warmup) | 233 ms |
| Warm | 31–47 ms |
| `vault_health` (orphans + weak_links) | < 2 s |

### `get_note_context` — Graph-Nachbarn

- Argus.md: 11 Nachbarn korrekt (5 outgoing + 6 incoming)
- Mneme.md: 5 outgoing korrekt

### `vault_health` — Orphan Detection

- 24 Orphan-Pages korrekt identifiziert
- Darunter 13 KITS-research_codex-Dateien ohne Wikilinks — echte Vault-Lücke, kein Mneme-Bug
- `weak_links`-Vorschläge inhaltlich sinnvoll (trotz Duplikat-Bug)
- `stale_notes: []` korrekt (Vault frisch restrukturiert)
- `near_duplicates: []` korrekt bei `threshold=0.85`

### MCP-Transport (streamable-http)

Kein Hang, keine Timeouts, keine Transport-Fehler über die gesamte Session. ✅

### `get_config`, `vault_stats`

Korrekte Ausgaben, Pfade korrekt redaktiert. ✅

---

## Release-Empfehlung

**v0.3.1 ist nach Fix von BUG 1 releasefähig.**

| Priorität | Item | Aufwand |
|---|---|---|
| **Blocker** | BUG 1: Over-Retrieval-Faktor in `search.py get_similar()` | 1 Zeile |
| Empfohlen | BUG 2: Note-Deduplikation in `gardener.py find_weakly_linked()` | ~10 Zeilen |
| Nice-to-have | OBS 1: `include_content` Parameter für `get_similar` | Klein |
| Backlog | OBS 2: `min_score` / `low_confidence` Flag | Klein–Medium |
| Backlog | OBS 3: `max_per_note` Parameter | Klein |

BUG 1 (Option B) ist ein sauberer 1-Zeiler mit null Performance-Overhead — der Fix sollte in den gleichen Commit wie der Release-Tag. BUG 2 ist optional für v0.3.1, spätestens v0.3.2.
