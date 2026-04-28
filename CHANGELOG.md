# Changelog

All notable changes to Mneme are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `Store.open_metadata_only()` classmethod for BM25/stats access without a
  real embedding model. Replaces the `Store(db, embedding_dim=1)` hack in
  `mneme status` and `mneme hook-search`, which baked a dummy `float[1]`
  into fresh DBs via `IF NOT EXISTS` and broke the next real reindex with a
  dimension mismatch.
- Schema v3: `notes.modified_at` column (file mtime, ISO-8601 UTC) separate
  from `notes.updated_at` (re-index timestamp). Auto-migrates v2 DBs by
  backfilling `modified_at = updated_at` on first open — no manual reindex
  required. `find_stale_notes` now uses
  `COALESCE(modified_at, updated_at)` so a full reindex no longer makes
  stale notes look fresh.
- Gardener contract test: pins the exact field names the Obsidian plugin
  consumes (`suggested_links`, `note_a.path`, `note_b.path`, …). Any future
  rename fails the build instead of silently breaking the Health modal.

### Changed
- `mneme search` and `mneme similar` now route through the shared
  `serialize_results()` helper (moved from `server.py` to `search.py`), so
  the CLI output matches the MCP tool and REST responses: `relevance_pct`,
  `clean_snippet` sanitation, and the heading-path fallback for empty
  snippets. Replaces the hand-rolled `content[:1500]` truncation.
- `mneme search` / `similar` CLI flag: the old `--json` flag had
  `default=True` meaning it was logically always on (dead text branch).
  Replaced with `--text` for plain-text output; JSON remains the default.
- `install_hooks` reconciles the matcher set instead of deduplicating by
  command string. The old logic saw an existing `mneme hook-search` command
  and skipped adding further entries, so going from `['Read']` to
  `['Read','Bash']` silently kept only `Read`. It now removes Mneme-owned
  entries first and re-installs exactly the requested matchers; user-owned
  hooks in the same event are preserved. Codex review follow-up 2026-04-19.
- Obsidian plugin Auto-Search dropdown now applies the backend workflow
  first and only persists the local `autoSearchMode` on success, rolling the
  dropdown UI back if the backend call fails. Prevents the plugin from
  claiming a mode that CLAUDE.md / hooks never adopted.
- `find_near_duplicates` samples deterministically (sorted path prefix)
  instead of `random.sample`. The same vault now produces the same report;
  `sample_size` is configurable (default 30).
- Obsidian plugin `health-modal.ts` reads the real backend shape:
  `weakly_linked[].suggested_links` (not `suggestions`),
  `near_duplicates[].note_a.path` / `note_b.path` (not `path_a` / `path_b`).
  The Vault Health panel rendered `undefined` at these points before.
- Obsidian plugin settings send list-typed config values
  (`auto_search.hook_matchers`, `health.exclude_patterns`) as JSON arrays —
  `config.py` rejects comma-strings, so user edits were silently discarded.
- Obsidian plugin Auto-Search dropdown routes through the real
  `setAutoSearchMode()` workflow (emits a Notice on success/failure) instead
  of only writing `auto_search.mode` to the config file and skipping the
  side-effects.
- MCP Resources (`mneme://vault/stats`, `/tags`, `/graph-summary`) now run
  through `_check_init()` and return a JSON error when the server is still
  initializing, matching tool behaviour. Previously they raised
  `KeyError: 'store'` on stdio cold-start reads.
- Plugin `autoStartServer` docs + `keepServerRunningAfterClose` comment
  aligned with the real `types.ts` defaults (autoStart on, persistence off).

### Fixed
- BM25 multi-token queries now use the documented OR recall semantics.
  `Store._sanitize_fts5_query` was joining quoted tokens with whitespace,
  which FTS5 interprets as **implicit AND** — any query containing a
  stopword or rare token returned zero hits even when the topic words
  matched. Tokens are now joined with explicit ` OR `, matching the
  docstring's stated intent (`'KI-Consulting' → '"KI" OR "Consulting"'`).
  BM25 ranking still surfaces multi-match docs first, so the recall
  expansion does not muddy ranking. Behaviour change for downstream
  consumers: `bm25_search` may now return more hits for queries that
  previously returned `[]`; verify if you rely on the empty-result
  signal. Discovered via KITS retriever Gold-v2 eval — multi-token
  trader-language queries (e.g. *"What is the spring in Wyckoff
  accumulation?"*) collapsed to zero BM25 hits despite clean FTS5
  matches.

## [0.3.1] - 2026-04-18

Launch-prep release: HTTP transport, Obsidian-plugin auto-start with
in-process fast-path, security hardening from a 5-agent parallel review,
watcher rewrite for bulk-save scenarios, plugin test suite, and a
README restructure driven by fresh-user feedback. See also:
`.github/workflows/ci.yml` (Python 3.11/3.12 on Ubuntu+Windows, plugin
tests, sdist/wheel build).

### Added
- HTTP transport (`streamable-http`) via FastMCP. Opt-in — stdio remains the
  default. `mneme serve --transport streamable-http` binds loopback on
  `127.0.0.1:8765` (`/mcp` + `/health`), pre-warms the embedding model at
  startup so the first request is fast.
- `/health` endpoint reports `status`, `model_loaded`, `db_size_mb`, and any
  init error — suitable for autostart readiness probes.
- REST fast-path for in-process callers: `POST /api/v1/search`, `/similar`,
  `/stats`, `/vault-health`, `/reindex`. Explicitly **not** an MCP replacement
  — external MCP clients continue to use `/mcp`. Saves the JSON-RPC session
  handshake for the Obsidian plugin (same Python process, shared state).
- `server` config section gains `host` and `port` fields.
- Obsidian plugin: auto-start HTTP server on Obsidian load, wait for
  `/health` warmup, couple to Obsidian lifecycle (server stops on unload
  unless `keepServerRunningAfterClose` is on). New settings:
  `serverPort` (default 8765), `autoStartServer`, `keepServerRunningAfterClose`.
- Obsidian plugin: HTTP fast-path with automatic CLI fallback — eliminates
  the 2-3s per-query CLI cold-start. `probeHealth` validates response shape
  and caps body at 4 KB to detect a port-squatter.
- `raw-transformers` embedding provider
  (`mneme.embeddings.raw_transformers.RawBgeM3Provider`) built directly on
  `transformers.AutoModel` + `torch`. Produces the same BGE-M3 dense
  embeddings (CLS pooling, L2-normalized, 1024-dim) as the
  `sentence-transformers` provider but without pulling in `sklearn`/`scipy`.
  Opt in via `mneme update-config embedding.provider raw-transformers`.
  Motivated by slow Windows `LoadLibrary` of `scipy.special` in
  Electron-spawned subprocess contexts.
- `scripts/verify_provider_parity.py` — dev-only byte-parity check (float32,
  CPU) between the two embedding providers.
- Progress bar for first-run indexing (`mneme setup`, `mneme reindex`) —
  shows per-file progress so multi-minute full reindexes no longer look
  frozen.
- `mneme setup` wizard prompts for transport choice (stdio vs
  streamable-http) with explanatory text for each.
- Windows autostart helpers: `scripts/install-autostart-windows.ps1` and
  `scripts/uninstall-autostart-windows.ps1` register/remove a Task Scheduler
  entry that launches the HTTP server via `pythonw.exe` at user logon.
- Env vars: `MNEME_DEBUG=1` (faulthandler + granular import logs),
  `MNEME_ALLOW_NETWORK=1` (opt out of offline mode),
  `MNEME_ALLOW_NONLOOPBACK=1` (required to bind non-loopback).
- Rotating file log: `mneme-server.log` (10 MB, 3 backups, INFO level).
- Obsidian plugin test suite (vitest + obsidian stub): 26 tests covering the
  path-guard allowlist, `/health` probe branches, and config-update
  debouncing.
- Python tests: `test_paths.py` (28 new), `test_cli_serve_hardening.py` (6 new),
  `test_server_http.py` (14 new, including the host-header-bypass regression),
  `test_watcher.py` (+3 for the global-coalescing-debounce).
- GitHub Actions CI (`.github/workflows/ci.yml`): Python 3.11/3.12 matrix on
  Ubuntu + Windows, plugin tests, sdist + wheel build with `twine check` on
  every push/PR. Runs on tag pushes matching `v*`.

### Changed
- Watcher rewritten from per-path Timer dict to a global-coalescing debounce
  (single `Timer` + `set[Path]` pending). Bulk-save scenarios (Obsidian
  Sync pull, git merge, rsync) now batch into one index pass instead of N
  serialized calls through the SQLite write-lock. `max_defer=10.0` prevents
  starvation from continuous edits. `on_graph_change` callback fires once
  per batch (was N-times). Deletes remain synchronous — not debounced.
- Plugin `updateConfig` calls debounced 400 ms — avoids per-keystroke CLI
  spawn when typing in the settings panel.
- `create_server` state bag typed with `ServerState` TypedDict — replaces
  the untyped dict.
- `update_config` rolls back its in-memory mutation if persisting to disk
  fails (was leaving the server running on a config that wasn't saved).
- `vault_health` rejects unknown check names (was silently returning an
  empty result, masking typos like `checks=["orphan"]` instead of `orphans`).
- `search_notes` validates the `after` cutoff at the tool boundary (clearer
  error than a deep-stack date-parse failure).
- Config: per-key numeric range validation via `_CONFIG_VALUE_CONSTRAINTS`
  — prevents `update_config` from setting runtime values out of spec (e.g.
  `top_k = 10000`, `rrf_k = -1`).
- Watcher exposes `on_graph_change` callback so centrality-cache invalidation
  fires on live edits, not only manual reindex.
- README restructured per fresh-user review: 60-second Quick-Start for
  Claude Desktop at the top, Zero-Cloud as the headline feature, separate
  sections for the three client integrations (Claude Desktop, Obsidian
  plugin, Claude Code), env-vars reference table, FAQ (8 entries),
  expanded troubleshooting, uninstall section, CHANGELOG link.
- Obsidian plugin ships its own README with pre-built-release install
  (Option A) and build-from-source (Option B) paths.
- `background_init` parameter renamed to `eager_init` for clearer semantics.
- Legacy `startServer` / pre-HTTP stdio code removed. `atexit` cleanup guarded
  to stdio transport only.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` Phase-1 entries
  marked as historical snapshots — no longer living specs.

### Fixed
- Plugin `updateConfig` now surfaces CLI failures (was silently dropping
  non-zero exit codes — settings would appear saved but have no effect).
- Plugin reindex gated on server warm state — was previously firing against
  a cold server and returning misleading errors.
- CLI Windows error 6 (`ERROR_INVALID_HANDLE`): `_silenced_stdout` process-wide
  `os.dup2(devnull, 1)` corrupted Windows console CRT state. Now
  TTY-aware — skips the redirect on interactive console.
- `mneme setup` wizard accepts `stdio` or `streamable-http` input after the
  new transport prompt was added.

### Security
- **`/health` Host-header prefix-match bypass**: the initial check used
  `startswith("127.0.0.1")`, which matches `127.0.0.1.evil.com` (classic
  DNS-rebind). Replaced with a rigorous parser: strip port, strip IPv6
  brackets, lowercase, reject control characters and whitespace, then
  exact-match against `{"127.0.0.1", "localhost", "::1"}`. Regression tests
  cover `127.0.0.1.evil.com`, null-byte injection, CRLF, and IPv6 bracket
  parsing.
- **FastMCP `@custom_route` middleware gap**: FastMCP only runs the
  TransportSecuritySettings check inside `StreamableHTTPSessionManager` —
  custom routes (`/health`, `/api/v1/*`) don't inherit it. Shared
  `_rest_guard()` function now runs the loopback host-check + init-complete
  check at the top of every custom route.
- **Obsidian plugin `spawn()` RCE surface**: plugin `data.json` lives inside
  the Obsidian vault and can travel via Obsidian Sync / Obsidian-Git /
  iCloud / Dropbox. A compromised vault template could set `mnemePath` to
  an arbitrary binary. Allowlist now blocks UNC paths, relative paths,
  traversal (`..`), wrong basename (only `mneme` / `mneme.exe` accepted),
  and the `mneme`-prefix bypass (e.g. `mneme-evil`).
- Plugin spawns Mneme with an explicit env whitelist (no `process.env`
  blanket inheritance — prevents leaking `AWS_*` / `OPENAI_API_KEY` etc. to
  the child) and hardcoded `--host 127.0.0.1` in argv (prevents a
  manipulated `data.json` from binding `0.0.0.0`).
- `MCP_FORBIDDEN_SECTIONS` now includes `server` — prevents a malicious MCP
  prompt from rewriting `server.host` or `server.port` via `update_config`.
- CLI `serve` refuses non-loopback bind unless `MNEME_ALLOW_NONLOOPBACK=1`
  is set. Pre-bind port-collision probe so errors are clear, not a stacktrace.

### Fixed (Live-Test Feedback, Round 1)

- **`get_similar` empty for large notes** (critical). The over-retrieval
  factor `top_k * 3` was too small for notes with many chunks. A note with
  N chunks could fill all `top_k * 3` slots in the vector search before the
  path filter ran, leaving `filtered[]` empty. Fix: over-retrieval now
  scales with `n_own_chunks + (top_k * 3) + 10` so neighbour candidates
  survive the path filter. Particularly affected project-hub MOCs and
  large Daily-Note collections.
- **`get_similar` duplicated neighbours by chunk** (minor). The method
  returned per-chunk results — a neighbour note with N relevant chunks
  appeared N times in the output. Now deduplicates by `note_path`, keeping
  the highest-scoring chunk per neighbour. Fixes duplicate entries in
  Gardener `weak_links` suggestions (same note listed 3× with different
  chunk scores) and in the MCP `get_similar` tool.
- **Plugin CLI-fallback noise leak**. When the HTTP fast-path was
  unreachable and the plugin fell back to `execFile("mneme", …)`, tqdm
  progress bars, HuggingFace Hub spinners, ROCm `UserWarning`s, and
  `torch_dtype` deprecation warnings leaked into stderr and were
  surfaced verbatim as the error message. CLI spawns now set
  `TQDM_DISABLE=1`, `HF_HUB_DISABLE_PROGRESS_BARS=1`,
  `TRANSFORMERS_VERBOSITY=error`, `PYTHONWARNINGS=ignore`. Error stderr
  is sanitized before display: progress bars and warning lines are
  filtered out, last 3 meaningful lines shown.
- **Ribbon icon color**. Plugin ribbon icon now renders in the brand
  gold (`#C9A84C`) matching the banner wordmark. Fill is hardcoded on
  the addIcon `<g>` so it takes effect regardless of Obsidian theme
  or CSS timing — a previous CSS-only attempt didn't render reliably
  across themes.
- **Plugin HTTP-fast-path visibility**. Startup now emits a Notice
  confirming whether the HTTP fast-path engaged (`HTTP-Fast-Path aktiv
  (Port X)`) or why it fell back (e.g. `Auto-Start ist deaktiviert`).
  Silent-fallback-to-CLI was the root cause of reported UI errors
  where users didn't realise their searches were hitting the CLI cold
  path. Fallback decisions are also logged to `console.warn` for
  devtools inspection.
- **Plugin CLI timeout bumped to 120s** for search/similar. 30s was
  too aggressive for BGE-M3 cold-load + search on some setups, causing
  the fallback path to report "Command failed" before the model even
  finished loading.
- **Plugin lazy HTTP discovery** — removed the dependency on a single
  `onStartup` success window for `setHttpPort()`. Every HTTP-capable
  method now probes `/health` on port 8765 before falling back, so the
  plugin self-heals if the startup race was lost (waitUntilWarm
  timeout, server still loading, etc.).
- **Plugin uses Obsidian's `requestUrl()` instead of `fetch()`** — *the*
  root cause of the "Command failed" reports in live testing. Browser
  `fetch()` from the Obsidian renderer (origin `app://obsidian.md`) to
  `http://127.0.0.1:8765` is a cross-origin request. Any POST with
  `Content-Type: application/json` triggers a CORS preflight that the
  FastMCP custom_route endpoints don't answer, so `fetch()` throws
  TypeError → the HTTP fast-path silently collapses → the CLI fallback
  *also* deadlocks on the SQLite write-lock held by the running server
  → the user sees "Mneme Fehler: Command failed" with no indication
  that the actual cause was CORS. `requestUrl()` is Obsidian's
  Node-level HTTP helper — it bypasses the renderer CORS stack and
  talks directly to the server. Applied to both `restCall()` and
  `probeHealth()`.
- **Plugin CLI timeout bumped to 120s** for search/similar (was 30s) —
  relevant only in the narrow case where the plugin's HTTP path is
  unreachable AND no Mneme server is running.

### Changed (Live-Test Feedback, Round 2)

Round-2 feedback from a quality-focused retrieval test pass surfaced
three UX issues that affect everyone using the tool — fixed here
rather than deferred to v0.3.2:

- **`relevance_pct` field in all search responses**. Raw RRF scores
  are structurally small (0.01-0.03) and carry no standalone meaning
  — absolute numbers like `0.015` read as "all results are miserable"
  even when they're the best matches in the vault. Every MCP tool
  (`search_notes`, `get_similar`) and REST endpoint
  (`/api/v1/search`, `/api/v1/similar`) now returns `relevance_pct`
  alongside `score`: top result is always 100%, others drop off
  proportionally. The raw `score` stays in the output for debugging
  and power users. Applied consistently across all four serialization
  boundaries so LLM clients see the same calibrated number as the
  Plugin-UI score badge.
- **`diversify_by_file` cap in `search_notes`**. The live test found
  a 70-page research document filling 4 of 5 top-k slots with deep
  code chunks, pushing dedicated domain notes out entirely. Results
  from a single note are now capped at 2 chunks (tightened from the
  initial 3 after a retest showed 3/5 still felt monotone on narrow
  topics), applied after RRF fusion and before the top-k slice (and
  as input to the reranker, so the reranker's candidate pool is
  already diverse). The best chunks per note survive the cap;
  ordering within and across notes is preserved.
- **`clean_snippet` for result content**. Previous `content[:1500]`
  truncation dumped raw markdown including fenced code blocks and
  table rows — noisy in LLM context windows and unreadable in the
  plugin preview. Snippets are now 200 chars of first-meaningful
  prose: context header (`[Title: ... | Folder: ...]`) stripped,
  fenced code blocks stripped, table rows dropped, whitespace
  collapsed, cut at a sentence boundary when one falls in the last
  40% of the budget.
- **Heading-path fallback for empty snippets**. Chunks that are pure
  code or tables clean to an empty string. The serializer now falls
  back to `heading_path` (or `note_title`) so every result carries
  something human-readable in `content` — no more blank previews.

None are breaking changes: `score` stays, `content` stays (shorter),
new `relevance_pct` is additive. `max_per_file` default of 2 is a
runtime behaviour change but only re-orders results within the same
top-k that was already returned — no search misses anything it
couldn't before.

## [0.3.0] - 2026-04-17

*Internal milestone — never published. Superseded by 0.3.1, which is the
actual PyPI debut under the `obsidian-mneme` package name (the short
`mneme` slug was already taken on PyPI by an unrelated project —
`mneme-cli` by [@tolism](https://github.com/tolism/mneme)). Import path
stays `import mneme`, the CLI command stays `mneme`.*

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

[Unreleased]: https://github.com/MakaveliGER/obsidian-mneme/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/MakaveliGER/obsidian-mneme/releases/tag/v0.3.1
[0.3.0]: https://github.com/MakaveliGER/obsidian-mneme/releases/tag/v0.3.0
[0.2.0]: https://github.com/MakaveliGER/obsidian-mneme/releases/tag/v0.2.0
