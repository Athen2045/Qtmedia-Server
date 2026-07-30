from private_search import search as search_module
from private_search.search import (
    ADAPTERS,
    SearchCandidate,
    VideoResult,
    adapter_for_host,
    canonical_url,
    deduplicate,
    filter_rejection_reason,
    impersonate_for_url,
    is_duration_label,
    is_video_candidate,
    relevance_score,
    search_adapter,
)


class _FakeResponse:
    """Stands in for a streamed response: search_adapter reads bodies via
    http_client.read_text(), so the body arrives through iter_content()."""

    def __init__(self, text, status_code=200):
        self._body = text.encode()
        self.status_code = status_code
        self.ok = status_code < 400
        self.encoding = "utf-8"
        self.url = "https://example.test/search"
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def close(self):
        self.closed = True

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self, html):
        self._html = html
        self.responses = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        response = _FakeResponse(self._html)
        self.responses.append(response)
        return response


def test_configured_adapters_have_expected_url_shapes():
    adapters = {adapter.name: adapter for adapter in ADAPTERS}
    assert adapters["TNAFlix"].make_search_urls("test title")[0].endswith(
        "/search?what=test+title"
    )
    assert adapters["YouJizz"].make_search_urls("test title")[0].endswith(
        "/tags/test-title-1.html"
    )
    assert adapters["YouPorn"].make_search_urls("test title")[0].endswith(
        "/porntags/test-title/"
    )


def test_deduplicate_keeps_highest_quality_result():
    low = VideoResult("Same Title", "https://one.test/1", "One", None, 720, 1000)
    high = VideoResult("same-title", "https://two.test/2", "Two", None, 1080, 800)
    assert deduplicate([low, high]) == [high]


def test_relevance_score_ranks_exact_match_above_partial_match():
    exact = relevance_score("Skylar Vox PMV", "Skylar Vox PMV")
    partial = relevance_score("Skylar Vox Oil PMV Compilation", "Skylar Vox PMV")
    unrelated = relevance_score("Completely Different Video", "Skylar Vox PMV")
    assert exact > partial > unrelated


def test_deduplicate_with_query_ranks_the_closest_title_first_even_at_lower_quality():
    """"Most accurate title first" means matching the query text, not
    picking whichever result happens to have the highest resolution."""
    exact_match_low_quality = VideoResult(
        "Skylar Vox PMV", "https://one.test/1", "One", None, 480, 1000
    )
    unrelated_high_quality = VideoResult(
        "Some Other Video Entirely", "https://two.test/2", "Two", None, 2160, 9000
    )
    ranked = deduplicate([unrelated_high_quality, exact_match_low_quality], "Skylar Vox PMV")
    assert ranked[0] == exact_match_low_quality


def test_filter_reason_is_specific():
    result = VideoResult("Bimbo title", "https://example.test/video/1", "Test", 5, 720, 0)
    assert filter_rejection_reason(result, ["missing"], [], 0) == "include filter"
    assert filter_rejection_reason(result, [], ["bimbo"], 0) == "exclusion"
    assert filter_rejection_reason(result, [], [], 10) == "minimum views"


def test_canonical_url_removes_tracking_parameters():
    url = "https://example.test/video/1?from=search&q=bimbo&quality=hd#player"
    assert canonical_url(url) == "https://example.test/video/1?quality=hd"


def test_xhamster_creator_pages_are_not_video_candidates():
    xhamster = next(adapter for adapter in ADAPTERS if adapter.name == "XHamster")
    assert not is_video_candidate(xhamster, "/creators/videos/example")
    assert is_video_candidate(xhamster, "/videos/example")


def test_adapter_for_host_matches_configured_and_www_hosts():
    assert adapter_for_host("xhamster.com").name == "XHamster"
    assert adapter_for_host("www.xhamster.com").name == "XHamster"
    assert adapter_for_host("m.xhamster.com").name == "XHamster"
    assert adapter_for_host("example.test") is None


def test_spankbang_scopes_extraction_to_the_results_container(tmp_path, monkeypatch):
    """Links from the site-wide nav dropdown (same on every page, unrelated
    to the query) must not be scraped as search results."""
    html = """
    <html><body>
    <ul class="nav-wrapper">
        <li><a href="/aaaaa/video/nav-dropdown-item">Nav trending item</a></li>
    </ul>
    <div id="search_page">
        <a href="/bbbbb/video/real-result">Real search result</a>
    </div>
    </body></html>
    """
    spankbang = next(adapter for adapter in ADAPTERS if adapter.name == "SpankBang")
    monkeypatch.setattr(search_module, "SEARCH_CACHE", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(search_module.http_client, "new_session", lambda impersonate=None: _FakeSession(html))
    monkeypatch.setattr(search_module.http_client, "get", lambda session, url, **kwargs: session.get(url))

    candidates = search_adapter(spankbang, "test query")

    urls = [candidate.url for candidate in candidates]
    assert any("real-result" in url for url in urls)
    assert not any("nav-dropdown-item" in url for url in urls)


def test_search_adapter_streams_the_body_and_closes_the_response(tmp_path, monkeypatch):
    """The search page is pulled in bounded chunks rather than as one
    whole-body copy, and the response is released once parsed."""
    html = '<html><body><a href="/studio/a-title/video123">A real title</a></body></html>'
    tnaflix = next(adapter for adapter in ADAPTERS if adapter.name == "TNAFlix")
    session = _FakeSession(html)
    kwargs_seen = {}

    def fake_get(_session, url, **kwargs):
        kwargs_seen.update(kwargs)
        return _session.get(url)

    monkeypatch.setattr(search_module, "SEARCH_CACHE", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(search_module.http_client, "new_session", lambda impersonate=None: session)
    monkeypatch.setattr(search_module.http_client, "get", fake_get)

    candidates = search_adapter(tnaflix, "test query")

    assert kwargs_seen["stream"] is True
    assert [candidate.title for candidate in candidates] == ["A real title"]
    assert all(response.closed for response in session.responses)


def test_search_adapter_skips_the_start_delay_on_a_cache_hit(tmp_path, monkeypatch):
    """The stagger only spreads real network calls; a cached site returns at once."""
    html = '<html><body><a href="/studio/a-title/video123">A real title</a></body></html>'
    tnaflix = next(adapter for adapter in ADAPTERS if adapter.name == "TNAFlix")
    monkeypatch.setattr(search_module, "SEARCH_CACHE", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(search_module.http_client, "new_session", lambda impersonate=None: _FakeSession(html))
    monkeypatch.setattr(search_module.http_client, "get", lambda session, url, **kwargs: session.get(url))
    search_adapter(tnaflix, "test query")

    slept = []
    monkeypatch.setattr(search_module.time, "sleep", slept.append)
    cached = search_adapter(tnaflix, "test query", start_delay=5.0)

    assert [candidate.title for candidate in cached] == ["A real title"]
    assert slept == []


def test_impersonate_for_url_uses_the_hosting_adapters_profile():
    # SpankBang is the adapter configured with a non-default profile, because
    # its bot detection rejects the shared Chrome one.
    assert impersonate_for_url("https://spankbang.com/abcde/video/some-title") == "safari184"
    assert impersonate_for_url("https://www.tnaflix.com/studio/a/video1") is None
    assert impersonate_for_url("https://unconfigured.example/video/1") is None


def test_ydl_options_impersonates_every_request_not_just_the_generic_extractor():
    """Site-specific extractors (YouPorn, TNAFlix) fetch their own webpages;
    the old generic-only extractor_args left those unimpersonated."""
    options = search_module.ydl_options("safari184")
    assert "extractor_args" not in options
    if search_module.http_client.HAS_CURL_CFFI:
        assert str(options["impersonate"]) == "safari-18.4"
    else:
        assert "impersonate" not in options


def test_ydl_options_retries_transient_extractor_failures():
    options = search_module.ydl_options()
    assert options["retries"] == search_module.http_client.RETRY_ATTEMPTS
    assert options["extractor_retries"] == search_module.http_client.RETRY_ATTEMPTS
    assert options["socket_timeout"] == search_module.REQUEST_TIMEOUT


def test_is_duration_label_distinguishes_overlay_text_from_real_titles():
    assert is_duration_label("08:00 720p")
    assert is_duration_label("HD 3m")
    assert is_duration_label("29m")
    assert is_duration_label("RU 20:54")
    assert is_duration_label("1:10:49")
    assert not is_duration_label("Angry Big Boobs Milf Dominating Pocket-Sized Teen")
    assert not is_duration_label("Shelby Caldera and Ranie Mae amazing hole Cumsluts")


def test_search_adapter_prefers_the_descriptive_title_over_a_duration_label(tmp_path, monkeypatch):
    """Some sites wrap one video in a thumbnail anchor (duration-only text)
    and a separate text anchor (the real title). Whichever is scraped first
    must not permanently win the dedup and hide the real title."""
    html = """
    <html><body>
    <a href="/studio/real-title/video123">08:00 720p</a>
    <a href="/studio/real-title/video123" title="Shelby Caldera does a thing">Shelby Caldera does a thing</a>
    </body></html>
    """
    tnaflix = next(adapter for adapter in ADAPTERS if adapter.name == "TNAFlix")
    monkeypatch.setattr(search_module, "SEARCH_CACHE", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(search_module.http_client, "new_session", lambda impersonate=None: _FakeSession(html))
    monkeypatch.setattr(search_module.http_client, "get", lambda session, url, **kwargs: session.get(url))

    candidates = search_adapter(tnaflix, "test query")

    assert len(candidates) == 1
    assert candidates[0].title == "Shelby Caldera does a thing"


def test_search_page_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(search_module, "SEARCH_CACHE", tmp_path / "cache.sqlite3")
    search_module.init_cache()
    candidates = [SearchCandidate("XVideos", "Example", "https://example.test/video/1")]

    assert search_module.load_cached_candidates("XVideos:example") is None
    search_module.cache_candidates("XVideos:example", candidates)
    assert search_module.load_cached_candidates("XVideos:example") == candidates
