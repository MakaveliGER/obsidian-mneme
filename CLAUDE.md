# Mneme

## Vault
vault: D:\Vault\second-brain\second-brain
projekt: 02 Projekte/Eigenprojekte/Mneme/Mneme.md
workflow: 04 Ressourcen/Skills, Tech & Methoden/Workflows/Projekt-Workflow.md

## Kontext
Lokaler MCP-Server für semantische Obsidian-Vault-Suche (v0.3.0, PyPI-Name `obsidian-mneme`). Headless RAG — 8 MCP-Tools + 3 Resources + 3 Prompts, Hybrid Search (Vector BGE-M3 + BM25 → RRF), CrossEncoder Reranking + GARS (beide opt-in, default off), Wikilink-Graph, Gardener (Vault Health), Auto-Search (off/smart/always). Python 3.11+, FastMCP (stdio), SQLite + sqlite-vec + FTS5, Watchdog. 235 Tests, 19+ Module. GPU: Dynamic Backend Detection (auto/cpu/cuda), ROCm 87x Speedup (float16, RX 7900 XTX). Eval Baseline: Hit@1 65%, MRR 0.71. Obsidian Plugin gebaut (Settings, Search, Health, Status Bar). CLI: search, similar, health, get-config, update-config. Golden Dataset: 66 Q&A-Paare.
⚠️ Bei Stack-Änderungen oder Architektur-Pivots sofort aktualisieren — neue Sessions starten mit diesem Bild.

## Intent
Semantische Vault-Suche als lokaler MCP-Server — Claude fragt, Mneme liefert die relevanten Notizen. Portfolio-Projekt, eigenes IP, Enterprise-Brücke zu Hohenstein.
⚠️ Der Intent bestimmt jede Architekturentscheidung. Im Zweifel: Was dient dem Intent besser? Bei Scope-Erweiterungen: Zahlt das auf den Intent ein?

## Workflow-Contract
**Feature-Trigger:** "neue Funktion", "integrieren", "ersetzen durch", "umbauen auf", "Feature X einbauen", "wir brauchen Y", "X durch Y ersetzen".
→ Bei diesen Wörtern: **erst Spec + Plan schreiben, dann coden.** Keine Ausnahme.

- Spec → `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
- Plan → `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`
- Faustregel: Änderung > 15 Min oder Architektur-Auswirkung → Workflow. Sonst direkt.

## Projektregeln
- **Secrets ausschließlich in `.env`** — keine API Keys, Tokens oder Credentials in Config-Dateien, Code oder CLAUDE.md. Immer `os.environ` / `dotenv` nutzen. `.env.example` mit Platzhaltern committen, `.env` nie.
- **Python 3.11+** — kein 3.10-Support
- **src-Layout** — Code unter `src/mneme/`
- **sqlite-vec Constraint** — KNN-Queries unterstützen keine WHERE-Klausel. Vector Search: Over-Retrieval + Post-Filtering. BM25: Pre-Filtering via SQL JOIN.
- **Wikilink-Regex** — `\[\[([^\]|]+)(?:\|[^\]]+)?\]\]` — Pipe-Alias korrekt abtrennen
- **Config-Pfade** — via `platformdirs` (Cross-Platform)
- **Embeddings** — nur in sqlite-vec Virtual Table, nicht doppelt in chunks-Tabelle

## Compact Instructions

When compacting this conversation, preserve:
- Project intent and current phase
- All modified file paths and their current state
- Key architectural decisions made in this session
- Exact error messages and unresolved issues
- Remaining TODO items and next steps
- Active constraints or rules stated during session

## Session-Ende
Bei Session-Ende — alle 9 Punkte durchgehen:
1. **Status** aktualisieren (Phase, Meilensteine, Blocker)
2. **Intent-Check** — Hat sich der Intent verändert? Falls ja: in Vault-Projekt-Datei aktualisieren.
3. **Entscheidungen** — alle wichtigen der Session dokumentiert?
4. **Learnings** — was haben wir gelernt?
5. **Nächste Schritte** aktualisieren
6. **Features/Deliverables** — Status-Update
7. **Dashboard** — `status` im Frontmatter aktualisieren (Projekte.base auto-sync)
8. **Tasks** `01 Inbox/Tasks.md` aktualisieren falls relevant
9. **Memory** — Cross-Project Learnings → `.claude/memory/` (Typen: user, reference, project, feedback). Projektspezifisches → nur Vault.

Pfad Vault-Projekt-Datei: D:\Vault\second-brain\second-brain\02 Projekte\Eigenprojekte\Mneme\Mneme.md
