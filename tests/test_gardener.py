"""Tests for mneme.gardener — VaultGardener health checks."""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mneme.config import MnemeConfig, VaultConfig, ChunkingConfig
from mneme.embeddings.base import EmbeddingProvider
from mneme.gardener import VaultGardener
from mneme.indexer import Indexer
from mneme.search import SearchEngine
from mneme.store import Store

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DIM = 16


class MockEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for _ in texts:
            v = [random.gauss(0, 1) for _ in range(DIM)]
            n = math.sqrt(sum(x * x for x in v))
            vecs.append([x / n for x in v])
        return vecs

    def dimension(self) -> int:
        return DIM


def _make_store_and_indexer(vault: Path, tmp_path: Path):
    config = MnemeConfig(
        vault=VaultConfig(
            path=str(vault),
            glob_patterns=["**/*.md"],
            exclude_patterns=[".obsidian/**", ".trash/**"],
        ),
        chunking=ChunkingConfig(max_tokens=200, overlap_tokens=20),
    )
    db_path = tmp_path / "test.db"
    store = Store(db_path, embedding_dim=DIM)
    provider = MockEmbeddingProvider()
    indexer = Indexer(store=store, embedding_provider=provider, config=config)
    return store, indexer, provider, config


def _make_search_engine(store: Store, provider: EmbeddingProvider, config: MnemeConfig) -> SearchEngine:
    mock_search_cfg = MagicMock()
    mock_search_cfg.top_k = 10
    mock_scoring_cfg = MagicMock()
    mock_scoring_cfg.gars_enabled = False
    return SearchEngine(store, provider, mock_search_cfg, reranker=None, scoring_config=mock_scoring_cfg)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def gardener_vault(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    # Orphan (keine Links rein oder raus) — in a subfolder so it is NOT root-level
    sub = vault / "notes"
    sub.mkdir()
    (sub / "orphan.md").write_text(
        "---\ntags: [test]\n---\n## Orphan\n\nIsolated note.",
        encoding="utf-8",
    )

    # Well-connected notes
    (vault / "hub.md").write_text(
        "## Hub\n\n[[spoke1]] and [[spoke2]]",
        encoding="utf-8",
    )
    (vault / "spoke1.md").write_text(
        "## Spoke 1\n\n[[hub]]",
        encoding="utf-8",
    )
    (vault / "spoke2.md").write_text(
        "## Spoke 2\n\n[[hub]]",
        encoding="utf-8",
    )

    # Stale note — status aktiv, will be backdated after indexing
    (vault / "stale.md").write_text(
        "---\nstatus: aktiv\n---\n## Stale\n\nOld content.",
        encoding="utf-8",
    )

    return vault


@pytest.fixture
def gardener_setup(gardener_vault: Path, tmp_path: Path):
    """Index the gardener_vault and return (gardener, store)."""
    store, indexer, provider, config = _make_store_and_indexer(gardener_vault, tmp_path)
    indexer.index_vault(full=True)

    # Backdate stale.md's updated_at to 60 days ago
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    store._conn.execute(
        "UPDATE notes SET updated_at = ? WHERE path LIKE '%stale%'",
        (old_ts,),
    )
    store._conn.commit()

    search_engine = _make_search_engine(store, provider, config)
    gardener = VaultGardener(store, search_engine)
    return gardener, store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_find_orphans(gardener_setup):
    """orphan.md (in subfolder, no links) must be found; hub/spoke must not."""
    gardener, _ = gardener_setup
    orphans = gardener.find_orphans()

    orphan_paths = [o["path"] for o in orphans]
    assert any("orphan" in p for p in orphan_paths), (
        f"Expected orphan.md in results, got: {orphan_paths}"
    )
    assert not any("hub" in p for p in orphan_paths)
    assert not any("spoke" in p for p in orphan_paths)


def test_find_stale_notes(gardener_setup):
    """stale.md with old updated_at and status=aktiv must appear in stale list."""
    gardener, _ = gardener_setup
    stale = gardener.find_stale_notes(days=30)

    stale_paths = [s["path"] for s in stale]
    assert any("stale" in p for p in stale_paths), (
        f"Expected stale.md in results, got: {stale_paths}"
    )

    # Verify structure
    for item in stale:
        assert "path" in item
        assert "title" in item
        assert "status" in item
        assert "last_updated" in item
        assert "days_stale" in item
        assert item["days_stale"] > 0

    # Sorted by days_stale descending
    if len(stale) > 1:
        assert stale[0]["days_stale"] >= stale[-1]["days_stale"]


def test_find_near_duplicates_empty(gardener_setup):
    """With random embeddings and threshold=0.85 there should be no duplicates."""
    gardener, _ = gardener_setup
    duplicates = gardener.find_near_duplicates(threshold=0.85)
    # Random unit vectors are very unlikely to exceed 0.85 cosine similarity
    assert isinstance(duplicates, list)
    for dup in duplicates:
        assert "note_a" in dup
        assert "note_b" in dup
        assert "similarity" in dup
        assert dup["similarity"] >= 0.85


def test_full_report_structure(gardener_setup):
    """full_report() must return a dict with all 4 expected keys."""
    gardener, _ = gardener_setup
    report = gardener.full_report(stale_days=30, similarity_threshold=0.85)

    assert isinstance(report, dict)
    assert "orphan_pages" in report
    assert "weakly_linked" in report
    assert "stale_notes" in report
    assert "near_duplicates" in report

    assert isinstance(report["orphan_pages"], list)
    assert isinstance(report["weakly_linked"], list)
    assert isinstance(report["stale_notes"], list)
    assert isinstance(report["near_duplicates"], list)


def test_find_orphans_excludes_patterns(tmp_path: Path):
    """Notes matching exclude_patterns must not appear in orphan results."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Regular orphan — should appear
    sub = vault / "notes"
    sub.mkdir()
    (sub / "orphan.md").write_text(
        "---\ntags: [test]\n---\n## Orphan\n\nIsolated note.",
        encoding="utf-8",
    )

    # Newsletter orphan — must be excluded
    newsletter = vault / "Newsletter"
    newsletter.mkdir()
    (newsletter / "digest.md").write_text(
        "## Digest\n\nWeekly digest.",
        encoding="utf-8",
    )

    store, indexer, provider, config = _make_store_and_indexer(vault, tmp_path)
    indexer.index_vault(full=True)
    search_engine = _make_search_engine(store, provider, config)

    gardener = VaultGardener(store, search_engine, exclude_patterns=["**/Newsletter/**"])
    orphans = gardener.find_orphans()
    orphan_paths = [o["path"] for o in orphans]

    assert any("orphan" in p for p in orphan_paths), (
        f"Expected orphan.md in results, got: {orphan_paths}"
    )
    assert not any("Newsletter" in p or "digest" in p for p in orphan_paths), (
        f"Newsletter/digest.md must be excluded, got: {orphan_paths}"
    )


def test_exclude_patterns_windows_backslashes(tmp_path: Path):
    """Paths with backslashes (Windows) must still match forward-slash patterns."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Simulate Windows path in DB: "05 Daily Notes\2026\note.md"
    daily = vault / "05 Daily Notes" / "2026"
    daily.mkdir(parents=True)
    (daily / "note.md").write_text("## Daily\n\nA daily note.", encoding="utf-8")

    store, indexer, provider, config = _make_store_and_indexer(vault, tmp_path)
    indexer.index_vault(full=True)
    search_engine = _make_search_engine(store, provider, config)

    gardener = VaultGardener(store, search_engine, exclude_patterns=["05 Daily Notes/**"])
    orphans = gardener.find_orphans()
    orphan_paths = [o["path"] for o in orphans]

    assert not any("Daily" in p or "note" in p for p in orphan_paths), (
        f"Daily note must be excluded by pattern, got: {orphan_paths}"
    )


def test_exclude_patterns_empty_no_filtering(tmp_path: Path):
    """With empty exclude_patterns all orphaned notes in subfolders are reported."""
    vault = tmp_path / "vault"
    vault.mkdir()

    newsletter = vault / "Newsletter"
    newsletter.mkdir()
    (newsletter / "digest.md").write_text(
        "## Digest\n\nWeekly digest.",
        encoding="utf-8",
    )

    store, indexer, provider, config = _make_store_and_indexer(vault, tmp_path)
    indexer.index_vault(full=True)
    search_engine = _make_search_engine(store, provider, config)

    gardener = VaultGardener(store, search_engine, exclude_patterns=[])
    orphans = gardener.find_orphans()
    orphan_paths = [o["path"] for o in orphans]

    assert any("digest" in p or "Newsletter" in p for p in orphan_paths), (
        f"Expected digest.md in results with no filtering, got: {orphan_paths}"
    )


def test_vault_health_selective_checks(gardener_setup):
    """Selective checks: only orphans check runs, other keys absent."""
    from unittest.mock import patch

    gardener, store = gardener_setup

    # Patch gardener into server state via a minimal create_server call
    from mneme.config import MnemeConfig, VaultConfig, DatabaseConfig
    from mneme.server import create_server

    db_path = store.db_path

    config = MnemeConfig(
        vault=VaultConfig(path=str(db_path.parent)),
        database=DatabaseConfig(path=str(db_path)),
    )

    with patch("mneme.server.get_provider") as mock_get_provider, \
         patch("mneme.server.VaultGardener") as mock_gardener_cls:

        mock_provider = MagicMock()
        mock_provider.dimension.return_value = DIM
        mock_get_provider.return_value = mock_provider

        # Inject our real gardener
        mock_gardener_cls.return_value = gardener

        server = create_server(config)

    # Find vault_health tool and call it
    tool_fn = server._tool_manager._tools["vault_health"].fn

    result = tool_fn(checks=["orphans"])
    assert "orphan_pages" in result
    assert "weakly_linked" not in result
    assert "stale_notes" not in result
    assert "near_duplicates" not in result
