# Performance, Search, and CLI UX Research

Date: 2026-08-16  
Scope: Python HTTP downloads, relevance/ranking, and simplified terminal guidance  
Source policy: primary sources only (official library documentation, standards, and first-party references)

## Executive summary

- Keep a long-lived HTTP session for repeated requests to the same host. Requests sessions use urllib3 connection pooling and automatically reuse keep-alive connections; streamed responses must be fully consumed or explicitly closed before the connection can be reused.
- Stream large bodies directly to their destination with `iter_content()`. Choose a chunk size by measurement and workload; it is a memory/read-buffer size, not a guarantee about the exact chunks returned. Bound HTML/page bodies, but do not accumulate an entire media file in memory.
- Retry narrowly: connect failures and selected transient statuses such as 429/5xx, only for operations that are safe to repeat. Honor `Retry-After`, use capped exponential backoff with jitter, and stop after a small attempt budget. Retrying a read failure after bytes have been committed requires resume or integrity handling.
- Use bounded I/O concurrency for independent requests, with a per-host limit. Parallel byte-range downloads are an opt-in optimization, not a default: they require range support, `206`/`Content-Range` validation, and a strong validator before parts are combined.
- For title search, normalize and tokenize both indexed text and queries with the same rules. BM25 is a strong baseline for short fields such as titles; field weights and exact/phrase boosts can express product intent. Fuzzy search should be a bounded fallback for likely typos because term expansion can become expensive.
- A simplified CLI should expose one-shot commands with discoverable `--help`, typed arguments/options, useful defaults, concise examples, optional interactive prompts only when appropriate, and progress that does not corrupt machine-readable output.

## Repository context

The repository currently has:

- `Qtmedia/src/qtmedia/net/http_client.py`: a shared Requests/curl-cffi session factory, retries, `stream=True`, 8 KiB bounded HTML reads, an 8 MiB response cap, and explicit response closing.
- `Qtmedia/src/qtmedia/search/engine.py`: concurrent searches across site adapters, a small candidate cap, title normalization, in-memory relevance scoring/deduplication, and SQLite caches.
- `Qtmedia/src/qtmedia/app/cli.py`: Typer subcommands (`search` and `download`), Rich tables/prompts/progress, and a direct-download path delegated to yt-dlp.
- Existing dated Markdown documents under `docs/`; no `docs/research/` convention existed, so this note uses the requested fallback path.

The recommendations below are research findings and design guidance only. No code changes are included.

## 1. Speeding up Python HTTP downloads

### Connection reuse and pool sizing

Requests documents that a `Session` persists parameters and uses urllib3 connection pooling, so repeated requests to the same host can reuse the underlying TCP connection. Keep-alive connections are released back to the pool only after the response body has been read or the response has been closed. [Requests Advanced Usage — Session Objects and Keep-Alive](https://requests.readthedocs.io/en/stable/user/advanced/)

Practical guidance:

1. Create one session for a request sequence or worker/host scope, rather than calling the top-level convenience API for every request.
2. Reuse that session for fallback URLs and related page/API calls to the same origin.
3. Always close a response that is abandoned, especially when `stream=True`; a `with` block is the safest shape for conditional or partial reads.
4. If concurrency is added for one host, size the adapter/pool deliberately. urllib3 documents `maxsize` as the number of reusable connections, and `block=True` as the way to cap in-flight connections and avoid flooding a host. [urllib3 Connection Pools](https://urllib3.readthedocs.io/en/latest/reference/urllib3.connectionpool.html)
5. Do not assume that more sockets means more throughput. Extra connections add TLS, server load, memory, and rate-limit pressure; benchmark a small set of per-host limits.

Repo-specific assessment: the current per-adapter session scope already allows fallback requests for one adapter to reuse connections and closes the session after the adapter finishes. If multiple requests to the same host become concurrent, make the per-host limit and pool behavior explicit rather than simply raising the global worker count.

### Streaming and memory use

Requests recommends `Response.iter_content()` for streaming a response to a file and notes that `stream=True` avoids reading the whole response at once. Its API documentation also states that `chunk_size` controls how many bytes are read into memory and that the returned item size is not necessarily exactly that value. [Requests Quickstart — Raw Response Content](https://requests.readthedocs.io/en/latest/user/quickstart/) and [Requests API — `iter_content`](https://requests.readthedocs.io/en/latest/api/)

Use separate policies for different payload classes:

- Search HTML/JSON: `stream=True`, bounded iteration, a maximum body size, and close in `finally`. Accumulating a bounded page for parsing is reasonable.
- Large media: iterate and write each non-empty chunk directly to a temporary/target file; do not collect all chunks in a list or call `.content`.
- Unknown or adversarial responses: enforce a byte cap for metadata pages and fail closed on an incomplete/truncated parse.
- Chunk size: treat 8 KiB as a conservative starting point for small pages, then benchmark larger values for large files. The optimal value depends on network latency, TLS, storage, and parser/write behavior; the Requests documentation does not prescribe one universal number.

Repo-specific assessment: the current bounded `read_text()` pattern is appropriate for search pages and its close-on-exit behavior is important. It should not be copied unchanged to a large media path because joining all chunks recreates a whole-body allocation.

### Timeouts and failure classification

Requests does not time out by default. A timeout should be supplied for external requests; a tuple can separate connect and read timeouts. The read timeout is not a total-download deadline: it applies to waiting for data from the server. [Requests Quickstart — Timeouts](https://requests.readthedocs.io/en/latest/user/quickstart/) and [Requests Advanced Usage — Timeouts](https://requests.readthedocs.io/en/stable/user/advanced/)

For downloads, distinguish:

- connect/DNS/TLS failure before a response;
- response-header/status failure;
- a read stall or connection reset mid-body;
- an application-level integrity or size mismatch after transfer.

These classes need different retry/resume behavior. A successful status code does not prove that a complete file was received.

### Retries, backoff, and idempotency

Requests does not retry failed connections by default, but its documented `HTTPAdapter` pattern supports urllib3 `Retry` with status lists, allowed methods, and backoff. [Requests Advanced Usage — Automatic Retries](https://requests.readthedocs.io/en/stable/user/advanced/)

urllib3 documents that `Retry` has separate budgets for total, connect, read, redirect, and status failures; defaults to an allowlist of idempotent methods; can honor `Retry-After`; and uses exponential backoff when no server-directed delay is available. [urllib3 Retry reference](https://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html)

HTTP semantics provide the safety boundary: a client may automatically repeat an idempotent request after a communication failure, while it should not automatically retry a non-idempotent request unless it knows the operation is safe or can detect that it was not applied. [RFC 9110 §9.2.2 — Idempotent Methods](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2)

Recommended policy for GET-based search and download metadata:

- Retry a small, finite number of connect failures.
- Retry selected transient statuses, commonly 429, 502, 503, and 504; consider 500 only when the endpoint is known to be transient.
- Honor `Retry-After` for 429/503-style responses; otherwise use capped exponential backoff.
- Add jitter so concurrent workers do not wake and retry in lockstep.
- Do not retry permanent 4xx responses such as 401, 403, or 404 by default.
- Treat a mid-body read failure as a resume problem, not as permission to blindly restart and append.
- Surface the last failure after the attempt budget is exhausted, with enough context for the CLI to explain what happened.

Repo-specific assessment: the existing status set, small attempt count, linear backoff plus jitter, and explicit closure of superseded streamed responses are directionally sound. The main gap to watch is honoring server-provided `Retry-After` and distinguishing a restartable/resumable media transfer from a metadata retry.

### Chunking, resume, and parallel ranges

HTTP range requests are optional. RFC 9110 defines `Range`, `Accept-Ranges`, `Content-Range`, and `206 Partial Content`; `Accept-Ranges: bytes` advertises support, but a client must not assume every later request will return a partial response. [RFC 9110 §14 — Range Requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-14)

For resumable or parallel downloads:

1. Probe or issue a range request and verify the response status and `Content-Range` rather than assuming support.
2. Record a strong validator such as an ETag when available. RFC 9110 permits combining partial responses only when they share the same strong validator. [RFC 9110 §15.3.7.3 — Combining Parts](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.7.3)
3. Write each part to a known offset or separate temporary part, validate its byte range and length, then combine in order.
4. Fall back to a normal full GET when range support is absent, ignored, inconsistent, or the representation changes.
5. Limit the number and size of ranges. RFC 9110 warns that many small or overlapping ranges can be inefficient or resemble a denial-of-service pattern. [RFC 9110 §14.6 — Multipart Ranges](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.6)

Parallel range requests can reduce wall-clock time when one connection is the bottleneck and the server/CDN supports them well. They can also reduce performance or trigger throttling. That tradeoff is an inference from the protocol constraints and should be established with measurements against the actual origin, not enabled universally.

### Concurrency for independent requests

Python’s `ThreadPoolExecutor` is designed to execute callables asynchronously in a pool of threads, and the Python documentation explicitly describes thread pools as useful for overlapping I/O. It also warns about deadlocks when tasks wait on other futures. [Python `concurrent.futures` documentation](https://docs.python.org/3/library/concurrent.futures.html)

Use concurrency when requests are independent and latency dominates:

- Bound the global worker count.
- Bound concurrency per host/origin separately.
- Keep queueing/backpressure visible; do not submit unbounded work for an unbounded result set.
- Preserve deterministic result ordering at the presentation layer if users expect it, even if completion is out of order.
- Avoid nested future waits and avoid sharing mutable session state without an explicit ownership model.
- Stagger initial bursts only when the target sites or connection setup justify it; use pooling to remove repeated setup cost before adding more workers.

Repo-specific assessment: the existing worker pool and small per-site candidate cap are reasonable for fan-out across different sites. Increasing `SEARCH_WORKERS` is unlikely to fix slow single-host downloads; per-host connection limits, response streaming, cache hits, and retry behavior matter more.

## 2. Search relevance and ranking

### Tokenization and normalization

Elasticsearch’s first-party text-analysis documentation describes tokenization as splitting text into searchable terms and normalization as converting terms into a consistent form such as lowercase, stemming, or synonyms. It specifically recommends applying compatible analysis to both the indexed value and the query so their tokens match. [Elastic — Text analysis](https://www.elastic.co/docs/manage-data/data-store/text-analysis) and [Elastic — Index and search analysis](https://www.elastic.co/docs/manage-data/data-store/text-analysis/index-search-analysis)

Baseline title-search pipeline:

1. Unicode-aware case folding/lowercasing.
2. Tokenization that deliberately handles punctuation, separators, digits, hyphens, and underscores.
3. Optional diacritic folding when product expectations treat accented and unaccented forms as equivalent.
4. Optional stemming only when it improves measured title recall; stemming is language-sensitive and can over-match names.
5. Apply the same pipeline to stored titles and queries.
6. Preserve the original title for display and keep normalized tokens as a separate search representation.

SQLite FTS5 provides a useful local reference for title indexes: its default `unicode61` tokenizer is case-insensitive and removes Latin diacritics by default; it also supports configurable token characters, separators, Porter stemming, and a trigram tokenizer for substring matching. [SQLite FTS5 — Tokenizers](https://www.sqlite.org/fts5.html#tokenizers)

Repo-specific assessment: `normalize_title()` is simple and useful for ASCII-oriented deduplication, but it discards non-ASCII letters. If international or accented titles matter, a Unicode-aware tokenization/normalization policy would preserve more recall. Keep URL canonicalization separate from title normalization, as the two have different correctness rules.

### BM25 as a baseline

Elastic documents BM25 as the default similarity and describes it as TF/IDF-based with term-frequency normalization that is intended to work well for short fields such as names. [Elastic — Similarity settings / BM25](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity)

For a title-oriented corpus, BM25 is a sensible baseline because it rewards query terms that are informative in the corpus and controls the effect of repeated terms and document length. Product-level ranking can then add explicit signals such as:

- exact normalized-title match;
- exact phrase match;
- all query tokens present;
- token coverage and proximity;
- trusted source/site preference;
- recency or popularity only when those signals reflect the user’s goal.

SQLite FTS5 includes BM25 and supports per-column weights; its documentation shows weighting title-like columns more heavily than body-like columns. It also notes that FTS5’s returned BM25 value is negated, so lower numeric values are better, and that ordering by the hidden `rank` column can be faster than calling `bm25()` directly, especially with `LIMIT`. [SQLite FTS5 — `bm25()` and rank](https://www.sqlite.org/fts5.html#the_bm25_function)

Important implementation distinction: Elastic-style scores conventionally sort higher-first, while SQLite FTS5 BM25 sorts lower-first. Do not compare raw scores across engines without adapting the direction and calibration.

### Fuzzy matching

Elastic defines fuzzy matching in terms of Levenshtein edit distance and generates possible term expansions within the configured distance. It warns that a high `max_expansions`, especially with `prefix_length=0`, can cause poor performance, and notes that fuzzy queries may be disabled as expensive queries. [Elastic — Fuzzy query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-fuzzy-query)

Use fuzzy matching as a controlled recall tool:

- Run exact/normalized/phrase matching first.
- Apply fuzzy matching only to likely typo-bearing terms or when exact retrieval returns too few candidates.
- Keep edit distance small; use a length-aware policy rather than allowing arbitrary edits.
- Cap expansions and consider a non-zero prefix length for longer terms.
- Avoid fuzzy matching on short tokens, IDs, URLs, or common words where false positives dominate.
- Re-rank fuzzy candidates with exact token coverage and phrase signals.

For the current small, per-query candidate lists, a bounded in-memory edit-distance fallback is likely simpler than adding a general-purpose fuzzy index. If the local corpus grows, use an indexed engine’s bounded fuzzy facilities and measure latency/recall.

### Indexing and prefix search

An inverted index is valuable when the searchable corpus is large or repeatedly queried. SQLite FTS5 documents that complete-token lookups are fast, while prefix queries otherwise require a range scan; configured prefix indexes accelerate prefixes of selected lengths at the cost of extra index storage and write work. [SQLite FTS5 — Prefix indexes](https://www.sqlite.org/fts5.html#prefix_indexes)

If this repository evolves from remote result ranking to a durable local title index:

- Store display fields separately from indexed fields.
- Keep URLs/IDs as `UNINDEXED` metadata when they should not affect text relevance. [SQLite FTS5 — `UNINDEXED` columns](https://www.sqlite.org/fts5.html#the_unindexed_column_option)
- Add prefix indexes only if autocomplete or prefix queries are a real workload.
- Use one documented analyzer/tokenizer configuration and version it with the index schema.
- Build a small judged query set before tuning weights; measure recall of the desired result and rank position, not just a synthetic score.

Repo-specific assessment: the current SQLite cache avoids repeated network and yt-dlp inspection work, but it is not a full-text index. For the current small result sets, improving normalization, exact/phrase/token scoring, and source-aware tie-breaking is lower complexity than introducing FTS5. FTS5 becomes attractive if cached candidates accumulate into a substantial local corpus or if offline search is required.

## 3. Terminal CLI UX and simplified guidance

### Command shape and discoverability

Typer supports multiple commands/subcommands, command-specific arguments/options, generated help, and optional help output when no arguments are provided. [Typer — Commands](https://typer.tiangolo.com/tutorial/commands/) and [Typer — Command arguments](https://typer.tiangolo.com/tutorial/commands/arguments/)

GNU’s command-line interface standard recommends consistent long option names and requires the conventional `--help` and `--version` options for GNU-style programs. [GNU Coding Standards — Command-Line Interfaces](https://www.gnu.org/prep/standards/html_node/Command_002dLine-Interfaces)

For simplified guidance, prefer:

- one clear verb per operation: `qt search QUERY` and `qt download URL`;
- positional arguments for the primary object and named options for modifiers;
- a short help description for every command and option;
- useful defaults shown in help;
- predictable exit codes and concise diagnostics;
- `--version` for support/debugging and `--help` at both root and subcommand levels;
- a small number of short aliases only for frequently used options;
- examples in README/help for the two common paths before advanced flags.

Typer performs type conversion and reports invalid values as CLI errors, which is preferable to accepting malformed numbers and failing later in the network path. [Typer — CLI parameter types](https://typer.tiangolo.com/tutorial/parameter-types/)

### Prompts, automation, and progressive disclosure

Click, the underlying CLI toolkit family used by Typer, documents both option-integrated prompts and explicit prompts, including prompting only when a value was not supplied on the command line. It also advises against combining an automatic prompt with a multiple-value option. [Click — User Input Prompts](https://click.palletsprojects.com/en/stable/prompts/)

Recommended UX contract:

- Make the common path non-interactive and scriptable: `qt download URL` should not require a follow-up menu.
- Use an optional prompt only for a genuinely helpful next action after a search, and provide a clear blank/skip path.
- Do not prompt when stdin is not an interactive terminal; expose an option such as `--no-prompt` or a direct-selection mode for automation.
- Keep advanced filters behind options rather than making users learn a session menu.
- Validate selection ranges immediately and explain the correction in one line.

Repo-specific assessment: the current `search` command already has a simpler shape than the old REPL and uses typed Typer options. The remaining UX risk is that the post-search selection prompt can surprise scripts or piped use; the guidance should distinguish interactive terminal use from automation.

### Progress, output streams, and terminal capability

Rich’s progress documentation supports multiple tasks, configurable columns, byte-based progress, speed, and ETA; it recommends using `Progress` as a context manager so start/stop cleanup is reliable. It also supports indeterminate progress when the total is unknown. [Rich — Progress Display](https://rich.readthedocs.io/en/latest/progress.html)

Rich auto-detects terminal color capabilities, and its `Console(stderr=True)` mode separates error output from normal output. [Rich — Console API](https://rich.readthedocs.io/en/latest/console.html)

For this CLI:

- Show an indeterminate state while waiting for headers or metadata, then switch to byte totals when known.
- Display speed and ETA only when the data is meaningful; avoid rapidly changing noisy lines for tiny operations.
- Keep normal results and success messages on stdout; send warnings/errors to stderr so users can pipe results.
- Let Rich detect color support; do not force truecolor or ANSI sequences in non-terminal output.
- Keep tables compact, truncate or wrap long titles deliberately, and preserve the URL in a selectable/detail path rather than forcing it into every row.
- Use Rich prompts when interaction is intentional; `IntPrompt`/prompt validation loops until the input is valid. [Rich — Prompt](https://rich.readthedocs.io/en/latest/prompt.html)

### Suggested help text hierarchy

The shortest useful guidance can be:

```text
qt search QUERY [OPTIONS]       Search configured sites.
qt download URL                  Download one direct video URL.

Examples:
  qt search "title words"
  qt search "title words" --filter hd --exclude vr
  qt download https://example.test/video

Run `qt COMMAND --help` for command-specific options.
```

This follows the source-backed principles of subcommand-specific help, typed parameters, standard help/version affordances, and progressive disclosure. It is guidance for future documentation/UI refinement, not an implementation change.

## Prioritized takeaways for this repository

| Priority | Finding | Why it matters here |
| --- | --- | --- |
| High | Preserve session reuse and close every streamed response | Prevents repeated handshakes and keeps the pool reusable. |
| High | Keep retry budgets finite and honor `Retry-After` | Avoids retry storms and respects server throttling. |
| High | Stream large media directly; keep bounded accumulation only for small pages | Prevents memory growth and makes download size independent of RAM. |
| High | Make interactive prompting conditional on an interactive terminal | Keeps `qt` usable in scripts and pipelines. |
| Medium | Use consistent Unicode-aware title normalization for both query and title | Improves recall beyond ASCII-only titles. |
| Medium | Add exact/phrase/token coverage before fuzzy fallback | Improves precision and keeps fuzzy expansion bounded. |
| Medium | Consider FTS5 only when the cached corpus becomes substantial | Avoids adding indexing complexity before the workload needs it. |
| Medium | If adding same-host concurrency, cap the host pool and benchmark | Prevents connection floods and makes throughput measurable. |
| Conditional | Add parallel range downloads only for origins with reliable range/validator behavior | Correctness and server compatibility are prerequisites for speed. |

## Primary sources consulted

- [Requests Advanced Usage](https://requests.readthedocs.io/en/stable/user/advanced/)
- [Requests Quickstart](https://requests.readthedocs.io/en/latest/user/quickstart/)
- [Requests API reference](https://requests.readthedocs.io/en/latest/api/)
- [urllib3 Connection Pools](https://urllib3.readthedocs.io/en/latest/reference/urllib3.connectionpool.html)
- [urllib3 Retry reference](https://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html)
- [Python `concurrent.futures`](https://docs.python.org/3/library/concurrent.futures.html)
- [RFC 9110 — HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)
- [Elastic — Text analysis](https://www.elastic.co/docs/manage-data/data-store/text-analysis)
- [Elastic — Index and search analysis](https://www.elastic.co/docs/manage-data/data-store/text-analysis/index-search-analysis)
- [Elastic — Similarity settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity)
- [Elastic — Fuzzy query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-fuzzy-query)
- [SQLite FTS5 Extension](https://www.sqlite.org/fts5.html)
- [Typer — Commands](https://typer.tiangolo.com/tutorial/commands/)
- [Typer — Command arguments](https://typer.tiangolo.com/tutorial/commands/arguments/)
- [Typer — CLI parameter types](https://typer.tiangolo.com/tutorial/parameter-types/)
- [Click — Help pages](https://click.palletsprojects.com/en/stable/documentation/)
- [Click — User input prompts](https://click.palletsprojects.com/en/stable/prompts/)
- [Rich — Progress display](https://rich.readthedocs.io/en/latest/progress.html)
- [Rich — Console API](https://rich.readthedocs.io/en/latest/console.html)
- [Rich — Prompt](https://rich.readthedocs.io/en/latest/prompt.html)
- [GNU Coding Standards — Command-Line Interfaces](https://www.gnu.org/prep/standards/html_node/Command_002dLine-Interfaces)
