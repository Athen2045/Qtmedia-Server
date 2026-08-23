from qtmedia.search import engine as search_module
from qtmedia.search.engine import SearchCandidate, VideoResult
from qtmedia.search.runtime import (
    EphemeralSearchCache,
    SearchEvent,
    SearchRuntime,
    SqliteSearchCache,
)


def candidate(url="https://example.com/watch/1"):
    return SearchCandidate("Example", "Literal title", url)


def result(url="https://example.com/watch/1"):
    return VideoResult(
        title="Literal title",
        url=url,
        site="Example",
        view_count=123,
        max_height=720,
        max_tbr=2500.0,
        thumbnail_url="https://images.example/thumb.jpg",
    )


def test_ephemeral_cache_expires_values_without_creating_files(tmp_path):
    now = [100.0]
    cache = EphemeralSearchCache(
        ttl_seconds=10,
        max_entries=4,
        clock=lambda: now[0],
    )
    expected_candidates = [candidate()]
    expected_result = result()

    cache.save_candidates("literal-key", expected_candidates)
    cache.save_result("literal-url-key", expected_result)

    assert cache.load_candidates("literal-key") == expected_candidates
    assert cache.load_result("literal-url-key") == expected_result
    assert list(tmp_path.iterdir()) == []

    now[0] = 111.0
    assert cache.load_candidates("literal-key") is None
    assert cache.load_result("literal-url-key") is None


def test_ephemeral_cache_prunes_oldest_entry_at_its_bound():
    now = [100.0]
    cache = EphemeralSearchCache(
        ttl_seconds=60,
        max_entries=2,
        clock=lambda: now[0],
    )

    cache.save_result("first", result("https://example.com/watch/1"))
    now[0] = 101.0
    cache.save_result("second", result("https://example.com/watch/2"))
    now[0] = 102.0
    cache.save_candidates("third", [candidate("https://example.com/watch/3")])

    assert cache.load_result("first") is None
    assert cache.load_result("second") is not None
    assert cache.load_candidates("third") is not None


def test_sqlite_cache_round_trips_public_search_values(tmp_path):
    database = tmp_path / "state" / "search.sqlite3"
    cache = SqliteSearchCache(
        database,
        result_ttl_seconds=60,
        candidate_ttl_seconds=30,
        clock=lambda: 100.0,
    )
    expected_candidates = [candidate()]
    expected_result = result()

    cache.save_candidates("literal-key", expected_candidates)
    cache.save_result("literal-url-key", expected_result)

    assert cache.load_candidates("literal-key") == expected_candidates
    assert cache.load_result("literal-url-key") == expected_result


def test_search_runtime_emits_value_free_structured_events():
    received = []
    runtime = SearchRuntime(
        cache=EphemeralSearchCache(ttl_seconds=60, max_entries=2),
        emit=received.append,
    )
    event = SearchEvent(stage="inspection", site="Example", count=3, code="done")

    runtime.report(event)

    assert received == [event]
    assert vars(event) == {
        "stage": "inspection",
        "site": "Example",
        "count": 3,
        "code": "done",
    }


def test_search_adapter_uses_ephemeral_runtime_without_sqlite(tmp_path, monkeypatch):
    html = '<a href="/video/one">Literal result</a>'
    adapter = search_module.SiteAdapter(
        "Example",
        "https://example.com/search/{query}",
        r"/video/",
    )
    events = []
    output = []
    runtime = SearchRuntime(
        cache=EphemeralSearchCache(ttl_seconds=60, max_entries=10),
        emit=events.append,
        display=output.append,
    )

    class Response:
        ok = True

        def close(self):
            return None

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(search_module, "SEARCH_CACHE", tmp_path / "forbidden.sqlite3")
    monkeypatch.setattr(
        search_module.http_client,
        "new_session",
        lambda impersonate=None: Session(),
    )
    monkeypatch.setattr(
        search_module.http_client,
        "get",
        lambda session, url, **kwargs: Response(),
    )
    monkeypatch.setattr(search_module.http_client, "read_text", lambda response: html)

    first = search_module.search_adapter(adapter, "literal query", runtime=runtime)
    monkeypatch.setattr(
        search_module.http_client,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cached search must not use the network")
        ),
    )
    second = search_module.search_adapter(adapter, "literal query", runtime=runtime)

    assert first == second
    assert [item.title for item in second] == ["Literal result"]
    assert list(tmp_path.iterdir()) == []
    assert all(vars(event).keys() == {"stage", "site", "count", "code"} for event in events)
    assert output == []

