# Search, Download, and CLI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve search accuracy, reduce unnecessary network/yt-dlp work, make downloads faster when the source supports parallel fragments, and simplify the terminal workflow.

**Architecture:** Add a deep `search_quality` module that owns text normalization, token-aware filtering, and ranking. Keep site adapters as retrieval adapters, but rank before their bounded candidate cap. Centralize yt-dlp transfer policy in a shared options helper used by inspection and download paths, while keeping CLI rendering and exit-status decisions at the CLI seam.

**Tech Stack:** Python 3.11+, Typer, Rich, BeautifulSoup, Requests/curl_cffi, yt-dlp, RapidFuzz, SQLite cache, pytest, Ruff.

## Global Constraints

- Add `rapidfuzz>=3.0` to runtime dependencies.
- Keep the current federated remote-search model; do not add a persistent local FTS5 index.
- Keep candidate and worker counts bounded; do not enable unrestricted parallel byte-range downloads.
- Preserve existing user-generated files, runtime media, cache databases, and local settings.
- Direct inspection must not prompt for downloading.
- Invalid command input and operational failures must have concise actionable errors and non-zero status when the command cannot complete.
- Every production behavior change must have a focused test.

## File Map

- Create: `Qtmedia/src/qtmedia/search_quality.py` — normalization, token-aware term matching, ranking, and candidate ordering.
- Modify: `Qtmedia/src/qtmedia/search.py` — use the quality module, fix fallback/cap behavior, overlap Lustpress searches, initialize cache once, and defer PMVHaven API fallback.
- Modify: `Qtmedia/src/qtmedia/downloader.py` — share retry/timeout policy and expose safe fragment/resume configuration.
- Modify: `Qtmedia/src/qtmedia/cli.py` — optional direct-url query, no-prompt direct inspection, validated selection, and consistent command errors.
- Modify: `Qtmedia/src/qtmedia/config.py` — typed environment-backed transfer settings if needed by downloader policy.
- Modify: `pyproject.toml` — add RapidFuzz dependency.
- Modify: `tests/test_search.py` — search quality, fallback, cap, concurrency, and metadata fallback tests.
- Modify: `tests/test_downloader.py` — downloader policy tests.
- Modify: `tests/test_cli.py` — direct-url and prompt/exit-status tests.
- Modify: `README.md` — correct CLI identity and document simplified command examples.
- Create: `benchmarks/benchmark_search_quality.py` — deterministic local ranking benchmark with no network access.

---

### Task 1: Add the search-quality module

**Files:**
- Create: `Qtmedia/src/qtmedia/search_quality.py`
- Modify: `pyproject.toml`
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: title/query strings and `VideoResult`-compatible objects through callbacks or simple fields.
- Produces: `normalize_text(text: str) -> str`, `tokenize(text: str) -> tuple[str, ...]`, `term_matches(text: str, term: str) -> bool`, `relevance_score(title: str, query: str) -> tuple[float, ...]`, and `rank_results(results: Iterable[T], query: str, quality_key: Callable[[T], tuple[float, ...]]) -> list[T]`.

- [ ] **Step 1: Write failing tests for Unicode normalization, word-aware exclusions, and ranking.**

Add tests covering:

```python
def test_term_matching_does_not_match_inside_words():
    assert not term_matches("Maid Compilation", "ai")
    assert term_matches("AI Generated Video", "ai")

def test_exact_phrase_beats_partial_substring():
    assert relevance_score("cat blue dog", "cat dog") > relevance_score("educat dog", "cat dog")

def test_typo_tolerance_is_bounded_and_fast():
    assert relevance_score("Skylar Vox PMV", "Skyler Vox PMV") > relevance_score(
        "Completely unrelated title", "Skyler Vox PMV"
    )

def test_normalization_preserves_unicode_letters():
    assert tokenize("Beyoncé—Live") == ("beyoncé", "live")
```

- [ ] **Step 2: Run the focused tests and verify they fail for the new module.**

Run: `.\.venv\Scripts\pytest.exe tests\test_search.py -k "term_matching or exact_phrase or typo_tolerance or normalization_preserves" -q`

Expected: collection/import failure because `qtmedia.search_quality` does not yet exist.

- [ ] **Step 3: Add the RapidFuzz dependency.**

Add `rapidfuzz>=3.0` to `[project].dependencies` in `pyproject.toml`, then install the editable project using the repository virtual environment so the focused tests exercise the declared dependency.

- [ ] **Step 4: Implement the smallest quality module.**

Use `unicodedata.normalize("NFKC", text).casefold()` and a Unicode-aware token regex. Use RapidFuzz only after exact/phrase/token coverage signals are calculated. Return a tuple whose earlier fields represent stronger signals, so normal tuple comparison preserves the documented ranking order. Keep `term_matches` token/phrase-aware and use substring matching only for multi-token phrases where the phrase itself is present.

- [ ] **Step 5: Run the focused tests and the existing ranking tests.**

Run: `.\.venv\Scripts\pytest.exe tests\test_search.py -k "relevance or deduplicate or term_matching or exact_phrase or typo_tolerance or normalization_preserves" -q`

Expected: PASS.

- [ ] **Step 6: Commit the module and tests.**

```powershell
git add pyproject.toml Qtmedia/src/qtmedia/search_quality.py tests/test_search.py
git commit -m "feat: add token-aware search ranking"
```

### Task 2: Use quality ranking during retrieval and inspection

**Files:**
- Modify: `Qtmedia/src/qtmedia/search.py`
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: `search_quality` functions from Task 1 and existing `SiteAdapter`, `SearchCandidate`, and `VideoResult` types.
- Produces: the existing public `search_adapter`, `search_lustpress`, `search`, `filter_rejection_reason`, `relevance_score`, and `deduplicate` behavior with improved ordering and filtering.

- [ ] **Step 1: Add failing tests for the retrieval correctness bugs.**

Add tests that assert:

```python
def test_empty_successful_primary_page_tries_fallback(tmp_path, monkeypatch):
    # Primary returns HTTP 200 with no candidates; fallback returns one candidate.
    assert [item.title for item in search_adapter(adapter, "query")] == ["Fallback hit"]

def test_candidate_cap_keeps_best_titles_not_dom_order(tmp_path, monkeypatch):
    # Put more than MAX_CANDIDATES_PER_SITE weak links before one exact match.
    assert any(item.title == "Exact query title" for item in search_adapter(adapter, "query"))

def test_unknown_views_fail_a_positive_minimum():
    assert not passes_filters(VideoResult("title", "url", "site", None, 720, 1), [], [], 100)

def test_successful_yt_dlp_extraction_does_not_call_pmvhaven_api(monkeypatch):
    # Mock yt-dlp success and assert fetch_metadata is untouched.
    inspect_candidate(candidate)
```

- [ ] **Step 2: Run the new tests and verify they fail.**

Run: `.\.venv\Scripts\pytest.exe tests\test_search.py -k "fallback or candidate_cap or unknown_views or pmvhaven_api" -q`

Expected: FAIL on the current empty-page fallback, DOM-order cap, unknown-view, and eager metadata behavior.

- [ ] **Step 3: Extract candidate parsing and rank before capping.**

Keep the existing adapter URL rules and duration-label preference. After collecting the per-page deduplicated candidates, sort by `search_quality.relevance_score(candidate.title, query)` and then truncate to `MAX_CANDIDATES_PER_SITE`. Preserve page order only as a stable final tie-breaker.

- [ ] **Step 4: Retry fallback URLs after empty successful pages.**

Parse each URL response before deciding that the adapter succeeded. Continue to the next configured URL when the parsed candidate list is empty; cache only the first non-empty result or the final empty result after all URLs are exhausted. Always close streamed responses through the existing HTTP helper.

- [ ] **Step 5: Replace substring filters and correct unknown-view handling.**

Use `search_quality.term_matches` for include/exclude terms. Treat `view_count is None` as rejected when `min_views > 0`, because the program cannot verify the threshold. Keep `extra_text` available for adapter-provided titles.

- [ ] **Step 6: Make metadata fallback lazy.**

Attempt yt-dlp extraction first. Only call `fetch_metadata` for PMVHaven after yt-dlp raises `DownloadError`, then cache the API-derived fallback result.

- [ ] **Step 7: Overlap optional Lustpress requests and initialize cache once.**

Call `init_cache()` once at the beginning of `search()`. Submit the three Lustpress site requests to a bounded executor and merge their results while built-in adapter futures run. Do not share mutable sessions between workers; each HTTP task owns its session.

- [ ] **Step 8: Run search tests and a deterministic benchmark.**

Run: `.\.venv\Scripts\pytest.exe tests\test_search.py -q`

Run: `.\.venv\Scripts\python.exe benchmarks\benchmark_search_quality.py`

Expected: all search tests pass; the benchmark prints ranking timings for a fixed local corpus without network access.

- [ ] **Step 9: Commit the retrieval improvements.**

```powershell
git add Qtmedia/src/qtmedia/search.py tests/test_search.py benchmarks/benchmark_search_quality.py
git commit -m "perf: rank and filter search candidates before inspection"
```

### Task 3: Centralize and tune download transfer policy

**Files:**
- Modify: `Qtmedia/src/qtmedia/downloader.py`
- Modify: `Qtmedia/src/qtmedia/search.py`
- Modify: `Qtmedia/src/qtmedia/config.py` if settings are placed there
- Test: `tests/test_downloader.py`
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: existing URL-specific impersonation and output-path behavior.
- Produces: `build_ydl_options(video_url=None)` and `ydl_options(impersonate=None)` with consistent retry/timeout settings, resume support, and bounded fragment concurrency.

- [ ] **Step 1: Add failing tests for transfer policy parity.**

Assert that both option builders include the same retry count, extractor/fragment retry policy, socket timeout, `continuedl=True`, and an integer `concurrent_fragment_downloads` within the configured bound. Assert that `http_chunk_size` is absent unless its environment setting is explicitly configured.

- [ ] **Step 2: Run the focused downloader tests and verify the new assertions fail.**

Run: `.\.venv\Scripts\pytest.exe tests\test_downloader.py tests\test_search.py -k "ydl_options or build_ydl_options or transfer or retry" -q`

Expected: FAIL because downloader options currently lack retry/timeout parity and transfer tuning.

- [ ] **Step 3: Implement one shared transfer-options helper.**

Define a private helper that returns the common yt-dlp policy dictionary. Read `PRIVATE_SEARCH_CONCURRENT_FRAGMENTS` as a positive integer capped at 8, defaulting to 4. Read `PRIVATE_SEARCH_HTTP_CHUNK_SIZE` only when set and parse it as a positive byte size. Set `continuedl=True`, `retries`, `fragment_retries`, and `socket_timeout`; retain site-specific impersonation and output-template overrides at the caller.

- [ ] **Step 4: Run transfer tests and existing download tests.**

Run: `.\.venv\Scripts\pytest.exe tests\test_downloader.py tests\test_search.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the transfer policy.**

```powershell
git add Qtmedia/src/qtmedia/downloader.py Qtmedia/src/qtmedia/search.py Qtmedia/src/qtmedia/config.py tests/test_downloader.py tests/test_search.py
git commit -m "perf: share resilient yt-dlp transfer settings"
```

### Task 4: Simplify CLI behavior and documentation

**Files:**
- Modify: `Qtmedia/src/qtmedia/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: existing `search.inspect_direct_url`, `search.search`, and `downloader.download_video` functions.
- Produces: `qt search [QUERY] [--direct-url URL]`, `qt download URL`, validated selection behavior, and a documented `--no-prompt` option.

- [ ] **Step 1: Add failing CLI tests.**

Cover:

```python
def test_direct_url_does_not_require_query_or_prompt(): ...
def test_direct_url_does_not_download(): ...
def test_q_skips_download(): ...
def test_invalid_selection_returns_nonzero(): ...
def test_no_prompt_never_reads_stdin(): ...
```

- [ ] **Step 2: Run the focused CLI tests and verify the new behavior fails.**

Run: `.\.venv\Scripts\pytest.exe tests\test_cli.py -q`

Expected: current direct-url mode requires a query and prompts; `q` is invalid; invalid selections exit successfully.

- [ ] **Step 3: Make query optional and direct inspection non-interactive.**

Use an optional Typer argument. Require either a query or `--direct-url`, but not a missing pair. In direct-url mode, render the inspected result and return before `_prompt_and_download`.

- [ ] **Step 4: Add validated selection and `--no-prompt`.**

Accept blank, `q`, and `Q` as skip. On any other invalid value, print one actionable error to stderr and raise `typer.Exit(code=2)`. Add `--no-prompt` to search and skip prompting when set. Keep the prompt text short and explicit: `Download result [1-N], or press Enter/q to skip:`.

- [ ] **Step 5: Improve help and README examples.**

Describe the project as a terminal CLI. Document direct inspection as `qt search --direct-url URL`, explain that it does not download, and show `--no-prompt` for scripted searches. Keep responsible-use and FFmpeg guidance intact.

- [ ] **Step 6: Run CLI, full tests, lint, and compile checks.**

Run:

```powershell
.\.venv\Scripts\pytest.exe tests\test_cli.py -q
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m compileall -q src tests search.py download.py
```

Expected: all commands pass. If the virtual-environment executable path contains an accidental space from copying, rerun with the exact path `.venv\Scripts\pytest.exe`.

- [ ] **Step 7: Commit the CLI and documentation changes.**

```powershell
git add Qtmedia/src/qtmedia/cli.py tests/test_cli.py README.md
git commit -m "feat: simplify search and download CLI guidance"
```

### Task 5: Final integration review

**Files:**
- Review: all files changed by Tasks 1–4
- Test: full repository test and quality commands

- [ ] **Step 1: Inspect the final diff and ensure unrelated worktree files are untouched.**

Run: `git diff HEAD~4..HEAD --stat` and `git status --short`. Confirm `.claude/`, `var/`, and any pre-existing modified files not listed in the task map were not added to commits.

- [ ] **Step 2: Run the full verification suite.**

Run:

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m compileall -q src tests search.py download.py
```

Expected: PASS with no new warnings.

- [ ] **Step 3: Review the behavior manually without network access.**

Run `qt --help`, `qt search --help`, and `qt download --help`. Verify the examples and `--no-prompt` option are visible, and verify direct-url help does not require a dummy query.

- [ ] **Step 4: Report measured and unmeasured performance honestly.**

Report deterministic ranking benchmark results and reduced candidate-inspection work. State that real download throughput remains source-dependent and that fragment concurrency is configurable rather than universally faster.
