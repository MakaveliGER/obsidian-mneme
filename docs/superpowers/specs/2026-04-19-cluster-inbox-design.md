# Spec — cluster_inbox + Capture-to-Action-Gap

**Block:** 1 (Schnellwins)
**Aufwand:** S-M (4-8h)
**Status:** draft

## Problem

Die Inbox (`01 Inbox/`) füllt sich mit schnellen Captures: Web-Clippings, Telegram-Saves, Gedankenfetzen, Link-Dumps. Diese bleiben liegen und werden **nicht systematisch verarbeitet**, weil:
- Ohne Überblick ist jeder Eintrag einzeln zu bewerten = hoher Context-Switch-Cost
- Zusammenhänge zwischen Inbox-Items (3 Captures zum selben Thema) werden nicht erkannt
- Es fehlt eine Zuordnung "gehört zu welchem Projekt/Bereich" — User muss jede Datei einzeln verschieben

Ergebnis: Inbox als schwarzes Loch, 20+ Items alt, Capture-to-Action-Gap wächst.

## User Story

> Ich rufe `Mneme: Inbox clustern` auf. Mneme gruppiert meine Inbox-Items in 3-7 semantische Cluster (z.B. "KI-Tools", "Hohenstein-Material", "Urlaub-Recherche") und schlägt pro Cluster einen **Ziel-Ordner** im Vault vor. Ich akzeptiere/verwerfe pro Cluster oder pro Item. Für jedes Inbox-Item älter als N Tage zeigt Mneme zusätzlich "gehört wahrscheinlich zu Projekt X" mit 85% Konfidenz.

## Lösung

### Zwei verwandte Features, eine Implementierung

**1. `cluster_inbox()`** — semantisches Clustering der Inbox
**2. Capture-to-Action-Gap** — Einzel-Items mit Projekt-Match vorschlagen

Beide nutzen denselben Backend-Pfad (Embedding + Clustering/Similarity). Gemeinsam bauen, zwei Views im Plugin.

### Algorithmus
1. Liste aller Notizen in `01 Inbox/` (exclude_patterns respektieren).
2. Für jede Notiz: Durchschnitts-Embedding aller Chunks (wie `get_similar` intern).
3. Clustering: **HDBSCAN** (robust, findet automatisch Cluster-Anzahl, verwirft Outlier) — oder **KMeans(k=auto)** wenn HDBSCAN zu langsam.
4. Pro Cluster: berechne Zentrum-Embedding, suche top-3 ähnlichste Ordner im Vault (Ordner-Embedding = Durchschnitt aller Notizen im Ordner).
5. Outlier-Items (nicht in Cluster): individuell ranken gegen alle Projekt-Notizen in `02 Projekte/`.

### UI — Obsidian-Plugin
Neue View `Mneme: Inbox` — Sidebar-Tab:
- **Oben:** Cluster-Sektionen. Jede Sektion collapsible: `🗂 KI-Tools (4 Items) → 04 Ressourcen/Skills, Tech & Methoden/Tools/`. Click auf Cluster expandet Items. "Alle akzeptieren"-Button pro Cluster.
- **Unten:** "Alte Einzel-Items" (>7 Tage, nicht in Cluster). Pro Item: Titel, Vorschlag, "In Projekt X verschieben"-Button.

### Aktion
- **Akzeptieren:** Plugin verschiebt Datei per Obsidian-API (`app.vault.rename`) in Ziel-Ordner. Backlinks werden von Obsidian automatisch aktualisiert.
- **Ablehnen:** Item bleibt in Inbox, wird in nächster Analyse weniger priorisiert (via DB-Flag).

## Interface

### MCP-Tool

```python
def cluster_inbox(
    inbox_folder: str = "01 Inbox",
    min_cluster_size: int = 2,
    include_outliers: bool = True,
) -> dict
```

Response:
```json
{
  "clusters": [
    {
      "cluster_id": 1,
      "theme_hint": "KI-Tools",
      "items": [
        {"path": "01 Inbox/...", "title": "...", "age_days": 3}
      ],
      "suggested_folder": {
        "path": "04 Ressourcen/Skills, Tech & Methoden/Tools/",
        "confidence": 0.82
      }
    }
  ],
  "orphans": [
    {
      "path": "01 Inbox/...",
      "title": "...",
      "age_days": 12,
      "project_suggestion": {
        "path": "02 Projekte/Eigenprojekte/Argus",
        "confidence": 0.71
      }
    }
  ],
  "stats": {
    "total_inbox_items": 23,
    "clustered": 17,
    "orphaned": 6,
    "processing_time_ms": 450
  }
}
```

### REST-Endpoint
Gleicher Shape, `POST /api/v1/cluster-inbox`

### Plugin-Command
`Mneme: Inbox clustern` — öffnet die neue Inbox-View

## Daten

- **Keine Schema-Änderung** im ersten Wurf.
- **Optional (Phase 2):** neue Tabelle `inbox_decisions(path, action, timestamp)` um "abgelehnt"-State zu persistieren — sonst schlägt Mneme denselben Move wieder vor.

## Abhängigkeiten

- **Neue Python-Dependency:** `scikit-learn` (für HDBSCAN + Folder-Centroid-Berechnung). ~30MB, verträglich. Alternative: eigene Mini-Clustering-Impl (~50 LOC DBSCAN) — im Spec offen lassen.
- Keine andere Feature-Abhängigkeit.

## Test Plan

### Backend
- `test_cluster_inbox_groups_similar_items`: 3 Notizen zu "RAG", 2 zu "Urlaub" → 2 Cluster
- `test_cluster_inbox_outliers_get_project_suggestion`: einzelne Notiz ohne Cluster-Genossen → project_suggestion gesetzt
- `test_cluster_inbox_empty_inbox_returns_empty`: leerer Inbox-Ordner
- `test_cluster_inbox_honors_exclude_patterns`: `.gitkeep`, Templates etc. werden übersprungen
- `test_cluster_inbox_folder_confidence_ranking`: Cluster-Theme matcht richtigen Folder

### Plugin
- Mock-Response → View rendert Cluster + Orphans korrekt
- "Akzeptieren" → `app.vault.rename` wird mit richtigen Args gerufen
- Empty-State → "Inbox ist sauber 🎉"

### Live-Akzeptanz
- Inbox mit 20+ gemischten Items → sinnvolle 3-5 Cluster mit nachvollziehbaren Ordner-Vorschlägen

## Open Questions

1. **HDBSCAN vs. KMeans:** HDBSCAN ist schlauer aber Dependency-schwerer. Bei <50 Inbox-Items überschätzt. → Empfehlung: HDBSCAN wenn schon scikit-learn dabei, sonst DBSCAN-lite.
2. **Theme-Hint-Generierung:** Aus welchem Signal? → Optionen: (a) häufigste Tags in Cluster, (b) LLM-Call (teuer, out-of-scope), (c) Filename-N-Grams. → Empfehlung: (a) + Fallback (c), (b) geht in Block 3.
3. **Auto-Move Option:** Direkt verschieben ohne User-Bestätigung (Trust-Mode)? → Empfehlung: nein. User-in-the-Loop ist Kern-Wert.
4. **Scope "Inbox"-Ordner:** hardcoded `01 Inbox/` oder konfigurierbar? → Konfigurierbar via Settings.

## Out-of-Scope

- **Automatisches Mergen** von Cluster-Items zu einer MOC-Notiz (→ Berührung mit `build_moc`, Block 3)
- **LLM-generated Theme-Hints** (Block 3 wenn summarize_area mitkommt)
- **Historische Inbox-Analyse** ("wie viele Items hattest du letzten Monat?") — interessant, aber nicht Kern-Zweck
