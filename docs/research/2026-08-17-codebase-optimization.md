# Codebase optimization review

Date: 2026-08-17

## Scope

This review covered the Python application under `src/private_search`, its tests,
SQLite access, recent commit history, and the current working tree. The checked-in
application is a terminal CLI; it does not contain FastAPI routes, Dataverse SDK
usage, PostgreSQL queries, SQLAlchemy models, or async database I/O. Those requested
skill areas were therefore treated as non-applicable rather than used to justify
unrelated rewrites.

## Findings and changes

### Obsolete interactive menu

`private_search.app.cli.interactive_menu` and its five private menu helpers had no
production caller after both root entry points moved to `interactive_chat`. The
`qt` command surface is Typer-based (`search` and `download`), so the menu was a
duplicate presentation path retained only by two legacy tests. The menu code and
those tests were removed; the scriptable CLI behavior remains unchanged.

### Dead search helpers

`search.quality.rank_titles` and `search.engine.passes_filters` were present in the
initial implementation but had no runtime or test callers. The active search flow
uses `relevance_score` and `filter_rejection_reason` instead. Both orphaned helpers
were deleted, along with the `Iterable` import that only supported `rank_titles`.

The early candidate filter also accepted `filters` but intentionally ignored it;
that parameter was removed from the private helper and its sole call site. Include
filters remain applied after yt-dlp inspection, where the canonical title is known.

### Face-index serialization

`FaceIndex.upsert_faces` called `_pack_embedding` twice for every face while building
one SQLite row. The normalized embedding is now packed once, and the resulting bytes
and dimension are reused by the batch insert. The SQLite schema and stored values are
unchanged.

This remains a local, measurable optimization rather than a speculative redesign:
the application already uses one transaction and `executemany` for the batch write.
Python's `sqlite3` documentation describes `executemany` as repeatedly executing a
parameterized DML statement and documents the connection context manager's commit /
rollback behavior:

- <https://docs.python.org/3/library/sqlite3.html#sqlite3.Cursor.executemany>
- <https://docs.python.org/3/library/sqlite3.html#how-to-use-the-connection-context-manager>

The embedding representation continues to use Python's standard `struct` packing of
numeric values into bytes:

- <https://docs.python.org/3/library/struct.html>

## Verification

- `233 passed` after cleanup; the baseline was `235 passed` before removing the two
  obsolete menu tests.
- Ruff reported no issues for `src` and `tests`.
- Python bytecode compilation completed successfully.
- The dead-helper scan finds no remaining `rank_titles` or `passes_filters` symbols.

## Follow-up opportunities

The SQLite face search currently loads stored embeddings and computes cosine scores
in Python. That is appropriate for the current local index size and keeps the
implementation portable; changing it would require measured index cardinality and
an explicit vector-search dependency. No such evidence was present in the repository,
so it was not changed in this pass.
