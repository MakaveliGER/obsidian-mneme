"""Vault health analysis — find orphans, weak links, stale notes, near-duplicates."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from mneme.store import Store
from mneme.search import SearchEngine


class VaultGardener:
    def __init__(self, store: Store, search_engine: SearchEngine) -> None:
        self.store = store
        self.search = search_engine

    def full_report(
        self,
        stale_days: int = 30,
        similarity_threshold: float = 0.85,
    ) -> dict:
        """Run all health checks and return structured report."""
        return {
            "orphan_pages": self.find_orphans(),
            "weakly_linked": self.find_weakly_linked(top_k=10),
            "stale_notes": self.find_stale_notes(days=stale_days),
            "near_duplicates": self.find_near_duplicates(threshold=similarity_threshold),
        }

    def find_orphans(self) -> list[dict]:
        """Find notes with no incoming AND no outgoing links (fully isolated).

        Root-level files (no folder separator in path) like 'Vault-Index.md'
        are excluded — they are expected to be link-less hubs.
        """
        rows = self.store._conn.execute(
            """
            SELECT n.path, n.title, n.tags
            FROM notes n
            WHERE n.id NOT IN (SELECT DISTINCT source_id FROM links)
              AND n.id NOT IN (SELECT DISTINCT target_id FROM links)
            """
        ).fetchall()

        results = []
        for path, title, tags_json in rows:
            # Exclude root-level files (no "/" in path)
            if "/" not in path and "\\" not in path:
                continue
            results.append({
                "path": path,
                "title": title,
                "tags": json.loads(tags_json) if tags_json else [],
            })
        return results

    def find_weakly_linked(self, top_k: int = 10) -> list[dict]:
        """Find notes with few links that have semantically related but unlinked notes.

        For performance: only checks notes with <=1 link, capped at 20 candidates.
        """
        # Get notes with <=1 total link (outgoing + incoming), ordered by fewest links
        rows = self.store._conn.execute(
            """
            SELECT id, path, title, total_links FROM (
                SELECT n.id, n.path, n.title,
                       (
                         (SELECT COUNT(*) FROM links WHERE source_id = n.id) +
                         (SELECT COUNT(*) FROM links WHERE target_id = n.id)
                       ) AS total_links
                FROM notes n
            ) sub
            WHERE total_links <= 1
            ORDER BY total_links ASC
            LIMIT 20
            """
        ).fetchall()

        # Build set of already-linked note paths per note
        results: list[dict] = []

        for note_id, path, title, total_links in rows:
            # Collect paths of already-linked notes (outgoing + incoming)
            linked_paths: set[str] = set()
            for row in self.store._conn.execute(
                """SELECT n.path FROM links l JOIN notes n ON n.id = l.target_id WHERE l.source_id = ?""",
                (note_id,),
            ).fetchall():
                linked_paths.add(row[0])
            for row in self.store._conn.execute(
                """SELECT n.path FROM links l JOIN notes n ON n.id = l.source_id WHERE l.target_id = ?""",
                (note_id,),
            ).fetchall():
                linked_paths.add(row[0])

            similar = self.search.get_similar(path, top_k=3)
            suggestions = [
                {
                    "path": r.note_path,
                    "title": r.note_title,
                    "similarity": round(r.score, 4),
                }
                for r in similar
                if r.score > 0.3 and r.note_path not in linked_paths
            ]

            if suggestions:
                results.append({
                    "path": path,
                    "title": title,
                    "current_links": total_links,
                    "suggested_links": suggestions,
                })

        # Sort by number of suggestions descending, then limit
        results.sort(key=lambda x: len(x["suggested_links"]), reverse=True)
        return results[:top_k]

    def find_stale_notes(self, days: int = 30) -> list[dict]:
        """Find notes with status 'aktiv' that haven't been updated in >days days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.isoformat()

        rows = self.store._conn.execute(
            """
            SELECT path, title, frontmatter, updated_at
            FROM notes
            WHERE frontmatter LIKE '%"status": "aktiv"%'
              AND updated_at < ?
            ORDER BY updated_at ASC
            """,
            (cutoff_str,),
        ).fetchall()

        now = datetime.now(timezone.utc)
        results = []
        for path, title, frontmatter_json, updated_at in rows:
            fm = json.loads(frontmatter_json) if frontmatter_json else {}
            # Double-check: frontmatter LIKE can have false positives
            if fm.get("status") != "aktiv":
                continue
            try:
                updated_dt = datetime.fromisoformat(updated_at)
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            days_stale = (now - updated_dt).days
            results.append({
                "path": path,
                "title": title,
                "status": fm.get("status", ""),
                "last_updated": updated_at,
                "days_stale": days_stale,
            })

        results.sort(key=lambda x: x["days_stale"], reverse=True)
        return results

    def find_near_duplicates(self, threshold: float = 0.85) -> list[dict]:
        """Find pairs of notes that are semantically very similar (potential duplicates).

        Checks a sample of up to 30 notes. Each pair is reported only once.
        """
        all_paths = self.store.get_all_note_paths()
        sample = all_paths[:30]

        seen_pairs: set[frozenset[str]] = set()
        results: list[dict] = []

        for path in sample:
            similar = self.search.get_similar(path, top_k=3)
            for r in similar:
                if r.score < threshold:
                    continue
                pair = frozenset([path, r.note_path])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                # Get title for the source note
                note = self.store.get_note_by_path(path)
                source_title = note["title"] if note else path

                results.append({
                    "note_a": {"path": path, "title": source_title},
                    "note_b": {"path": r.note_path, "title": r.note_title},
                    "similarity": round(r.score, 4),
                })

        return results
