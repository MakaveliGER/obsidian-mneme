"""End-to-End Integrationstest für Mneme.

Testet den vollständigen Durchlauf von Setup über Indexierung bis zur Suche,
inklusive Wikilink-Graph, Gardener-Health-Check, inkrementellem Re-Index
und Auto-Search CLAUDE.md-Injection.
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mneme.auto_search import (
    CLAUDE_MD_MARKER_END,
    CLAUDE_MD_MARKER_START,
    inject_claude_md,
    remove_claude_md,
)
from mneme.config import (
    ChunkingConfig,
    HealthConfig,
    MnemeConfig,
    SearchConfig,
    VaultConfig,
)
from mneme.embeddings.base import EmbeddingProvider
from mneme.gardener import VaultGardener
from mneme.indexer import Indexer
from mneme.search import SearchEngine
from mneme.store import Store

# ---------------------------------------------------------------------------
# Konstanten & Helpers
# ---------------------------------------------------------------------------

DIM = 16


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministisch zufällige, normalisierte Vektoren (kein echtes ML-Modell)."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for _ in texts:
            v = [random.gauss(0, 1) for _ in range(DIM)]
            n = math.sqrt(sum(x * x for x in v))
            vecs.append([x / n for x in v])
        return vecs

    def dimension(self) -> int:
        return DIM


def _make_config(vault: Path, tmp_path: Path, exclude_patterns: list[str] | None = None) -> MnemeConfig:
    return MnemeConfig(
        vault=VaultConfig(
            path=str(vault),
            glob_patterns=["**/*.md"],
            exclude_patterns=exclude_patterns or [".obsidian/**", ".trash/**", ".claude/**"],
        ),
        chunking=ChunkingConfig(max_tokens=200, overlap_tokens=20),
        search=SearchConfig(top_k=10),
    )


def _make_store(tmp_path: Path, name: str = "test.db") -> Store:
    return Store(tmp_path / name, embedding_dim=DIM)


def _make_search_engine(store: Store, provider: EmbeddingProvider) -> SearchEngine:
    search_cfg = MagicMock()
    search_cfg.top_k = 10
    scoring_cfg = MagicMock()
    scoring_cfg.gars_enabled = False
    return SearchEngine(
        store=store,
        embedding_provider=provider,
        config=search_cfg,
        reranker=None,
        scoring_config=scoring_cfg,
    )


# ---------------------------------------------------------------------------
# Fixture: Integration Vault
# ---------------------------------------------------------------------------

@pytest.fixture
def integration_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()

    # Note 1: KI-Strategie (mit Tags, Wikilinks)
    (vault / "ki-strategie.md").write_text(
        "---\ntags: [ki, strategie, projekt]\nstatus: aktiv\n---\n"
        "## KI-Strategie\n\n"
        "Unsere KI-Strategie umfasst [[rag-pipeline]] und Machine Learning.\n"
        "Wir setzen auf lokale Modelle für maximale Datensouveränität.\n",
        encoding="utf-8",
    )

    # Note 2: RAG Pipeline (verlinkt von Note 1, verlinkt zurück)
    (vault / "rag-pipeline.md").write_text(
        "---\ntags: [ki, rag, tech]\n---\n"
        "## RAG Pipeline\n\n"
        "Retrieval Augmented Generation kombiniert Vektor-Suche mit LLM-Reasoning.\n"
        "Die Pipeline besteht aus Indexierung, Retrieval und Generierung.\n"
        "Wir nutzen [[ki-strategie]] als Grundlage.\n",
        encoding="utf-8",
    )

    # Note 3: Python Guide (isoliert, Orphan — in Unterordner)
    sub = vault / "guides"
    sub.mkdir()
    (sub / "python-basics.md").write_text(
        "---\ntags: [python, coding]\n---\n"
        "## Python Basics\n\n"
        "Python ist eine vielseitige Programmiersprache.\n"
        "Listen, Dictionaries und Funktionen sind Grundbausteine.\n",
        encoding="utf-8",
    )

    # Note 4: Meeting Notes (kein Frontmatter, Orphan)
    (vault / "meeting-2026-04.md").write_text(
        "## Meeting April\n\n"
        "Diskussion über Vault-Organisation und Wissensmanagement.\n"
        "Entscheidung für semantische Suche mit Mneme.\n",
        encoding="utf-8",
    )

    # Note 5: Newsletter (soll vom Health-Check excluded werden)
    news = vault / "Newsletter"
    news.mkdir()
    (news / "digest-01.md").write_text(
        "## Digest\n\nKI-News der Woche.",
        encoding="utf-8",
    )

    return vault


# ---------------------------------------------------------------------------
# Test 1: Vollständige Pipeline
# ---------------------------------------------------------------------------

def test_full_pipeline(integration_vault: Path, tmp_path: Path) -> None:
    """Config → Indexer → Index Vault → Search → Stats — alles in einem Durchlauf."""
    config = _make_config(integration_vault, tmp_path)
    store = _make_store(tmp_path)
    provider = MockEmbeddingProvider()
    indexer = Indexer(store=store, embedding_provider=provider, config=config)

    # --- Index ---
    result = indexer.index_vault(full=True)

    # Newsletter wird NICHT excluded (kein exclude_pattern dafür in config)
    assert result.indexed == 5, f"Erwartet 5 indexiert, bekommen: {result.indexed}"
    assert result.skipped == 0
    assert result.deleted == 0
    assert result.duration_seconds >= 0

    # --- Stats ---
    stats = store.get_stats(embedding_model="mock")
    assert stats.total_notes == 5
    assert stats.total_chunks > 0

    # --- Search ---
    search_engine = _make_search_engine(store, provider)
    results = search_engine.search("KI Strategie")

    assert len(results) >= 1, "Suche nach 'KI Strategie' lieferte keine Ergebnisse"
    note_paths = [r.note_path for r in results]
    # Mindestens eine der KI-Noten muss im Ergebnis sein
    assert any("ki-strategie" in p or "rag-pipeline" in p for p in note_paths), (
        f"Keine KI-relevante Note in Suchergebnissen: {note_paths}"
    )


# ---------------------------------------------------------------------------
# Test 2: Wikilink-Graph
# ---------------------------------------------------------------------------

def test_wikilink_graph(integration_vault: Path, tmp_path: Path) -> None:
    """Nach dem Index sind Wikilinks aufgelöst und bidirektional navigierbar."""
    config = _make_config(integration_vault, tmp_path)
    store = _make_store(tmp_path)
    provider = MockEmbeddingProvider()
    indexer = Indexer(store=store, embedding_provider=provider, config=config)

    result = indexer.index_vault(full=True)
    assert result.links_resolved >= 2, (
        f"Erwartet mind. 2 aufgelöste Links, bekommen: {result.links_resolved}"
    )

    # ki-strategie Note aus DB laden
    ki_note = store.get_note_by_path("ki-strategie.md")
    assert ki_note is not None, "ki-strategie.md nicht im Index gefunden"

    rag_note = store.get_note_by_path("rag-pipeline.md")
    assert rag_note is not None, "rag-pipeline.md nicht im Index gefunden"

    # Outgoing links von ki-strategie → rag-pipeline
    linked = store.get_linked_notes(ki_note["id"])
    linked_paths = [n["path"] for n in linked]
    assert "rag-pipeline.md" in linked_paths, (
        f"ki-strategie.md sollte auf rag-pipeline.md verlinken. Gefunden: {linked_paths}"
    )

    # Backlinks von rag-pipeline → ki-strategie
    backlinks = store.get_backlinks(rag_note["id"])
    backlink_paths = [n["path"] for n in backlinks]
    assert "ki-strategie.md" in backlink_paths, (
        f"rag-pipeline.md sollte Backlink von ki-strategie.md haben. Gefunden: {backlink_paths}"
    )

    # Bidirektional: rag-pipeline verlinkt auch auf ki-strategie
    rag_linked = store.get_linked_notes(rag_note["id"])
    rag_linked_paths = [n["path"] for n in rag_linked]
    assert "ki-strategie.md" in rag_linked_paths, (
        f"rag-pipeline.md sollte auf ki-strategie.md verlinken. Gefunden: {rag_linked_paths}"
    )


# ---------------------------------------------------------------------------
# Test 3: Vault Health — Orphans
# ---------------------------------------------------------------------------

def test_vault_health_finds_orphans(integration_vault: Path, tmp_path: Path) -> None:
    """Gardener findet isolierte Noten, respektiert exclude_patterns."""
    config = _make_config(integration_vault, tmp_path)
    store = _make_store(tmp_path)
    provider = MockEmbeddingProvider()
    indexer = Indexer(store=store, embedding_provider=provider, config=config)
    indexer.index_vault(full=True)

    search_engine = _make_search_engine(store, provider)

    # Newsletter-Verzeichnis aus Health-Check ausschließen
    gardener = VaultGardener(
        store=store,
        search_engine=search_engine,
        exclude_patterns=["Newsletter/**"],
    )

    orphans = gardener.find_orphans()
    orphan_paths = [o["path"] for o in orphans]

    # Orphan-Kandidaten: guides/python-basics.md und meeting-2026-04.md
    # meeting-2026-04.md ist root-level → wird von find_orphans() ignoriert (kein "/" im Pfad)
    # guides/python-basics.md ist in einem Unterordner → Orphan
    assert any("python-basics" in p for p in orphan_paths), (
        f"guides/python-basics.md sollte als Orphan erscheinen. Gefunden: {orphan_paths}"
    )

    # Newsletter/digest-01.md: excluded durch exclude_pattern
    assert not any("digest-01" in p for p in orphan_paths), (
        f"Newsletter/digest-01.md sollte durch exclude_pattern ausgeschlossen sein. Gefunden: {orphan_paths}"
    )

    # ki-strategie und rag-pipeline sind verlinkt — keine Orphans
    assert not any("ki-strategie" in p for p in orphan_paths), (
        f"ki-strategie.md sollte KEIN Orphan sein (hat Links). Gefunden: {orphan_paths}"
    )
    assert not any("rag-pipeline" in p for p in orphan_paths), (
        f"rag-pipeline.md sollte KEIN Orphan sein (hat Links). Gefunden: {orphan_paths}"
    )


# ---------------------------------------------------------------------------
# Test 4: Inkrementeller Re-Index
# ---------------------------------------------------------------------------

def test_incremental_reindex(integration_vault: Path, tmp_path: Path) -> None:
    """Erster Index: 5 indexed. Zweiter: 0/5 skipped. Nach Änderung: 1/4."""
    config = _make_config(integration_vault, tmp_path)
    store = _make_store(tmp_path)
    provider = MockEmbeddingProvider()
    indexer = Indexer(store=store, embedding_provider=provider, config=config)

    # Erster Durchlauf: alles neu indexiert
    first = indexer.index_vault(full=False)
    assert first.indexed == 5, f"Erster Index: erwartet 5, bekommen {first.indexed}"
    assert first.skipped == 0

    # Zweiter Durchlauf: nichts geändert → alles übersprungen
    second = indexer.index_vault(full=False)
    assert second.indexed == 0, f"Zweiter Index ohne Änderungen: erwartet 0, bekommen {second.indexed}"
    assert second.skipped == 5, f"Zweiter Index ohne Änderungen: erwartet 5 skipped, bekommen {second.skipped}"

    # Eine Note ändern
    (integration_vault / "ki-strategie.md").write_text(
        "---\ntags: [ki, strategie, projekt]\nstatus: aktiv\n---\n"
        "## KI-Strategie (aktualisiert)\n\n"
        "Unsere aktualisierte KI-Strategie umfasst [[rag-pipeline]] und Deep Learning.\n"
        "Wir setzen weiterhin auf lokale Modelle.\n",
        encoding="utf-8",
    )

    # Dritter Durchlauf: nur die geänderte Note re-indexiert
    third = indexer.index_vault(full=False)
    assert third.indexed == 1, f"Dritter Index nach Änderung: erwartet 1, bekommen {third.indexed}"
    assert third.skipped == 4, f"Dritter Index nach Änderung: erwartet 4 skipped, bekommen {third.skipped}"


# ---------------------------------------------------------------------------
# Test 5: Auto-Search CLAUDE.md
# ---------------------------------------------------------------------------

def test_auto_search_claude_md(integration_vault: Path) -> None:
    """inject_claude_md erstellt Datei mit Marker. remove_claude_md entfernt ihn. Idempotent."""
    target = integration_vault / "CLAUDE.md"
    assert not target.exists(), "CLAUDE.md sollte vor dem Test nicht existieren"

    # --- Erstes Inject: Datei wird neu erstellt ---
    changed = inject_claude_md(integration_vault)
    assert changed is True, "inject_claude_md sollte True zurückgeben (Datei neu erstellt)"
    assert target.exists(), "CLAUDE.md sollte nach inject_claude_md existieren"

    content = target.read_text(encoding="utf-8")
    assert CLAUDE_MD_MARKER_START in content, "Start-Marker fehlt in CLAUDE.md"
    assert CLAUDE_MD_MARKER_END in content, "End-Marker fehlt in CLAUDE.md"

    # --- Idempotenz: zweites Inject → keine Änderung ---
    changed_again = inject_claude_md(integration_vault)
    assert changed_again is False, "Zweites inject_claude_md sollte False zurückgeben (keine Änderung)"

    content_after_second = target.read_text(encoding="utf-8")
    assert content_after_second == content, "Inhalt sollte nach idempotenter Injection unverändert sein"

    # --- Remove: Marker wird entfernt ---
    removed = remove_claude_md(integration_vault)
    assert removed is True, "remove_claude_md sollte True zurückgeben (Marker entfernt)"

    content_after_remove = target.read_text(encoding="utf-8")
    assert CLAUDE_MD_MARKER_START not in content_after_remove, "Start-Marker sollte nach remove nicht mehr da sein"
    assert CLAUDE_MD_MARKER_END not in content_after_remove, "End-Marker sollte nach remove nicht mehr da sein"

    # --- Idempotenz remove: nochmal remove → keine Änderung ---
    removed_again = remove_claude_md(integration_vault)
    assert removed_again is False, "Zweites remove_claude_md sollte False zurückgeben (kein Marker mehr)"
