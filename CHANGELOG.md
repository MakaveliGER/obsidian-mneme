# Changelog

All notable changes to Mneme are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-04-17

PyPI debut under the `obsidian-mneme` package name (the short `mneme` slug
was already taken on PyPI by an unrelated project). Import path stays
`import mneme`, the CLI command stays `mneme`.

### Added
- `mneme init` as an alias for `mneme setup`.
- `mneme similar <path>` CLI command — semantic nearest-neighbour lookup for a
  given vault-relative note path.
- Global CLI error handler: concise messages by default, full tracebacks via
  `MNEME_DEBUG=1`.
- DB schema versioning (`_meta.schema_version`). Opening a legacy database
  raises `MnemeSchemaError` with a clear migration hint; `reindex --full`
  bumps the version after a successful full index.
- Troubleshooting section in the README and an expanded `.env.example`.
- Cache for `build_alias_map` — invalidated on insert/delete, kept valid for
  content-only updates. Removes the per-save O(N) scan on the watcher hot path.

### Changed
- MCP `update_config` now refuses to mutate the `embedding` and `reranking`
  sections; changing a model name could load arbitrary HuggingFace code via
  `trust_remote_code`. Use the CLI for those changes.
- MCP `search_notes` / `get_similar` / `get_note_context` now normalize paths
  and clamp `top_k` / `depth` / `similar_k` to sane upper bounds (DoS hardening).
- `search_notes` honours the `after` cutoff for both BM25 *and* vector results
  (was previously BM25-only, silently leaking old notes from the vector path).
- `apply_config_update` centralises the bool/int/float/list parser shared by
  CLI and MCP. Unknown bool values now raise instead of silently becoming
  `False`.
- Obsidian plugin "Similar notes" tab calls `get_similar` instead of running a
  title text search (previously returned title matches, not semantic neighbours).
- `hook-search` filters the file Claude is about to read out of its results.
- `install-hooks` refuses to write into a directory that isn't the configured
  vault unless `--force` is passed.
- Stored note paths are now always POSIX (`as_posix()`) — fixes path-based
  lookups (`get_similar`, `get_note_context`, hook self-filter) on Windows.
  Requires a full reindex for databases created before this change.

### Fixed
- `upsert_chunks` matched embedding-to-rowid via list index + `ORDER BY
  chunk_index`; now joined explicitly by `chunk_index` so the input list order
  doesn't matter.
- `delete_note` now wraps its two DELETE statements in `try / except / rollback`
  (was inconsistent with `upsert_chunks`).
- `chunks_vec` cleanup uses `executemany` point-lookups instead of an
  `IN (SELECT ...)` subquery — the sqlite-vec virtual table planned the
  subquery as a full scan (36x slower at 2000 notes).
- Gardener `find_weakly_linked` replaces per-row correlated subqueries and
  per-candidate N+1 lookups with a CTE plus two bulk joins.
- FTS5 sanitizer caps query to 1000 chars / 64 tokens.

## [0.2.0] - 2026-04-16

Initial public-facing release.

### Added
- Hybrid search: BGE-M3 vector + BM25 FTS5, fused with Reciprocal Rank Fusion.
- 8 MCP tools, 3 resources, 3 prompts (FastMCP over stdio).
- Obsidian plugin with settings, search view, health modal, and status bar.
- Auto-search modes (`off` / `smart` / `always`) plus `install-hooks`.
- Wikilink graph + Gardener (orphans, stale notes, weakly linked suggestions).
- CrossEncoder reranking and Graph-Aware Retrieval Scoring (both opt-in, kept
  disabled for small vaults where eval showed they hurt Hit@1).
- Dynamic GPU backend detection (`auto` / `cpu` / `cuda`); ROCm path tuned for
  AMD on Windows.
- Golden-dataset evaluator (`mneme eval`) with Hit@k and MRR metrics.

[Unreleased]: https://github.com/MakaveliGER/mneme/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/MakaveliGER/mneme/releases/tag/v0.3.0
[0.2.0]: https://github.com/MakaveliGER/mneme/releases/tag/v0.2.0
