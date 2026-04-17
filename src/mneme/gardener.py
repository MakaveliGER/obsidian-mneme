"""Vault health analysis — find orphans, weak links, stale notes, near-duplicates."""

from __future__ import annotations

import fnmatch
import json
import random
from datetime import datetime, timezone, timedelta

from mneme.store import Store
from mneme.search import SearchEngine


class VaultGardener:
    def __init__(
        self,
        store: Store,
        search_engine: SearchEngine,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        self.store = store
        self.search = search_engine
        self._exclude_patterns: list[str] = exclude_patterns if exclude_patterns is not None else []

    def _is_excluded(self, path: str) -> bool:
        """Return True if path matches any of the configured exclude patterns.

        Normalizes backslashes to forward slashes before matching.
        Handles ** glob patterns by checking path-prefix containment
        (fnmatch doesn't support ** as recursive globstar).
        """
        normalized = path.replace("\\", "/")
        for pattern in self._exclude_patterns:
            # Strip ** and trailing/leading slashes to get the directory name
            # "05 Daily Notes/**" → "05 Daily Notes"
            # "**/Newsletter/**" → "Newsletter"
            stripped = pattern.replace("**", "").strip("/")
            if not stripped:
                continue
            # Check if any path component sequence matches the stripped pattern
            if f"/{stripped}/" in f"/{normalized}/" or normalized.startswith(f"{stripped}/"):
                return True
            # Fallback: standard fnmatch for non-** patterns
            if "**" not in pattern and fnmatch.fnmatch(normalized, pattern):
                return True
        return False

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
            if self._is_excluded(path):
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
        # Single aggregated query: count outgoing + incoming links per note via
        # UNION ALL + GROUP BY (replaces per-row correlated subqueries that
        # went quadratic on large graphs).
        rows = self.store._conn.execute(
            """
            WITH link_counts AS (
                SELECT note_id, COUNT(*) AS cnt
                FROM (
                    SELECT source_id AS note_id FROM links
                    UNION ALL
                    SELECT target_id AS note_id FROM links
                )
                GROUP BY note_id
            )
            SELECT n.id, n.path, n.title, COALESCE(lc.cnt, 0) AS total_links
            FROM notes n
            LEFT JOIN link_counts lc ON lc.note_id = n.id
            WHERE COALESCE(lc.cnt, 0) <= 1
            ORDER BY total_links ASC
            LIMIT 20
            """
        ).fetchall()

        # Filter excluded and keep order-preserving id list
        candidates = [(nid, path, title, cnt) for nid, path, title, cnt in rows if not self._is_excluded(path)]
        if not candidates:
            return []

        # Bulk-load linked paths for all candidates in two queries instead of
        # 2 × N per-candidate queries.
        candidate_ids = [c[0] for c in candidates]
        placeholders = ",".join("?" * len(candidate_ids))
        linked_paths_by_note: dict[int, set[str]] = {nid: set() for nid in candidate_ids}

        for row in self.store._conn.execute(
            f"""SELECT l.source_id, n.path FROM links l
                JOIN notes n ON n.id = l.target_id
                WHERE l.source_id IN ({placeholders})""",
            candidate_ids,
        ).fetchall():
            linked_paths_by_note[row[0]].add(row[1])
        for row in self.store._conn.execute(
            f"""SELECT l.target_id, n.path FROM links l
                JOIN notes n ON n.id = l.source_id
                WHERE l.target_id IN ({placeholders})""",
            candidate_ids,
        ).fetchall():
            linked_paths_by_note[row[0]].add(row[1])

        results: list[dict] = []
        for note_id, path, title, total_links in candidates:
            linked_paths = linked_paths_by_note[note_id]
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
            if self._is_excluded(path):
                continue
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
        non_excluded = [p for p in all_paths if not self._is_excluded(p)]
        sample = random.sample(non_excluded, min(30, len(non_excluded)))

        seen_pairs: set[frozenset[str]] = set()
        results: list[dict] = []

        for path in sample:
            similar = self.search.get_similar(path, top_k=3)
            for r in similar:
                if r.score < threshold:
                    continue
                if self._is_excluded(r.note_path):
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
