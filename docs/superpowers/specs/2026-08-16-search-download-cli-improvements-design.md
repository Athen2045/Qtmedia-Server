# Search, Download, and CLI Improvements Design

**Date:** 2026-08-16

## Goal

Make the terminal search and download workflow faster, more accurate, and easier to operate without changing the project’s core purpose or adding a local search service.

## Current search method

The application uses federated web retrieval with local heuristic reranking:

1. Site adapters query configured sites concurrently.
2. BeautifulSoup parses result-page HTML and site-specific URL patterns select candidates.
3. SQLite caches search-page candidates and yt-dlp inspection results.
4. Candidate pages are inspected concurrently with yt-dlp.
5. Filters are applied to inspected metadata.
6. Results are deduplicated by normalized title.
7. Results are ordered by exact substring match, query-word coverage, `SequenceMatcher` similarity, and quality.

This is not currently BM25, SQLite FTS5, or an inverted-index search. The remote sites perform retrieval; this program performs local filtering and reranking.

## Design

### Search quality module

Introduce a focused ranking module behind a small interface. It will own Unicode-aware normalization, tokenization, word-aware exclusions, candidate scoring, and result ordering. RapidFuzz will provide fast fuzzy similarity for bounded typo tolerance.

The ranking order will prioritize:

1. normalized exact title;
2. exact phrase and token order;
3. all-token coverage;
4. token-set and partial similarity for likely typos;
5. quality and bitrate as tie-breakers.

Search-page candidates will be ranked before the per-site cap so DOM order cannot discard a better match. The existing candidate cap remains bounded to protect network and yt-dlp inspection cost.

Exclusion matching will be token/phrase-aware. A term such as `ai` will match a standalone token or phrase, not arbitrary substrings inside words such as `Maid`.

### Search retrieval and orchestration

Search adapters will continue to use bounded concurrent I/O, shared sessions per adapter, streamed bounded HTML reads, and finite jittered retries. If a fallback search URL returns HTTP 200 but no usable candidates, the next fallback will be attempted before caching the final result.

Optional Lustpress searches will run concurrently with each other and with built-in adapters. Cache initialization will happen once per top-level search rather than repeatedly in workers.

The implementation will not add SQLite FTS5 yet. The current cache stores a small remote-result working set rather than a durable local corpus, so in-memory token ranking provides the needed accuracy with less migration and maintenance cost.

### Download policy

Centralize yt-dlp transfer options so search inspection and direct downloading share retry and timeout policy. Add conservative, configurable fragment concurrency and resume support. An optional HTTP chunk-size setting will remain disabled unless explicitly configured because server behavior varies.

Parallel byte-range downloads are out of scope: they require range validation, strong validators, part integrity, and origin-specific benchmarking.

### CLI behavior

The CLI will expose the common one-shot paths clearly:

```text
qt search "title words"
qt download https://example.test/video
```

Direct inspection will support `qt search --direct-url URL` without a dummy query, will render one result, and will never prompt to download. Interactive result selection will accept blank input or `q`/`Q` to skip and will reject invalid selections with a concise non-zero CLI error. Non-interactive callers will be able to disable the follow-up prompt.

Normal result output and progress remain separate from actionable errors. README wording will identify the project consistently as a terminal CLI and document the supported command forms.

## Error handling

- Search transport failures remain isolated to the affected adapter and do not prevent other sources from returning results.
- Invalid URLs, missing FFmpeg, yt-dlp failures, and invalid CLI selections produce one actionable error with a non-zero status where the command cannot complete.
- User cancellation remains a normal, clearly reported outcome.
- Streamed responses are always consumed or closed so connection pools can reuse them.

## Testing and measurement

Add focused tests for:

- token-aware exclusion behavior;
- exact/phrase/token/fuzzy ranking order;
- ranking before the per-site candidate cap;
- empty-200 fallback behavior;
- concurrent Lustpress orchestration;
- PMVHaven metadata only on yt-dlp fallback;
- shared downloader retry/timeout options;
- fragment concurrency and resume configuration;
- direct-url no-query/no-prompt behavior;
- `q`/blank selection and invalid selection exit status.

Run the existing unit suite, Ruff, compile checks, and a small deterministic benchmark comparing ranking and candidate-processing work before and after the change. Network speed must not be claimed from synthetic tests; actual transfer speed remains dependent on the source, format, CDN, and server throttling.

## Scope boundaries

This change will not introduce a GUI, a persistent local full-text index, an external search provider, unrestricted parallel range downloads, or a broad unrelated refactor. Existing user-generated files and local runtime artifacts remain outside the change.
