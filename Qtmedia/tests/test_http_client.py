import requests

from qtmedia.net import http_client


class _Response:
    def __init__(self, status_code, body=b"", encoding="utf-8"):
        self.status_code = status_code
        self.encoding = encoding
        self.url = "https://example.test"
        self.closed = False
        self._body = body

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def close(self):
        self.closed = True


class _FlakySession:
    def __init__(self, failures_then_response):
        self._events = list(failures_then_response)

    def get(self, url, **kwargs):
        event = self._events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


def test_get_retries_transient_failures_then_succeeds(monkeypatch):
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)
    session = _FlakySession([requests.ConnectionError("reset"), _Response(200)])
    assert http_client.get(session, "https://example.test").status_code == 200


def test_get_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)
    session = _FlakySession([requests.ConnectionError("reset")] * http_client.RETRY_ATTEMPTS)
    try:
        http_client.get(session, "https://example.test")
    except requests.ConnectionError:
        pass
    else:
        raise AssertionError("expected the last error to propagate")


def test_get_retries_a_retryable_status_code_then_succeeds(monkeypatch):
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)
    session = _FlakySession([_Response(500), _Response(200)])
    response = http_client.get(session, "https://example.test")
    assert response.status_code == 200


def test_get_does_not_retry_a_non_retryable_status_code(monkeypatch):
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)
    session = _FlakySession([_Response(404)])
    response = http_client.get(session, "https://example.test")
    assert response.status_code == 404


def test_get_returns_last_response_after_exhausting_status_retries(monkeypatch):
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)
    session = _FlakySession([_Response(500)] * http_client.RETRY_ATTEMPTS)
    response = http_client.get(session, "https://example.test")
    assert response.status_code == 500


def test_get_closes_a_response_it_retries_past(monkeypatch):
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)
    superseded = _Response(500)
    session = _FlakySession([superseded, _Response(200)])
    http_client.get(session, "https://example.test")
    assert superseded.closed, "the retried-past body must not be left on the socket"


def test_backoff_is_jittered(monkeypatch):
    delays = []
    monkeypatch.setattr(http_client.time, "sleep", delays.append)
    monkeypatch.setattr(http_client.random, "uniform", lambda _low, high: high)
    session = _FlakySession([_Response(500)] * http_client.RETRY_ATTEMPTS)
    http_client.get(session, "https://example.test")
    assert delays == [
        http_client.RETRY_BACKOFF_SECONDS + http_client.RETRY_JITTER_SECONDS,
        http_client.RETRY_BACKOFF_SECONDS * 2 + http_client.RETRY_JITTER_SECONDS,
    ]


def test_read_text_reassembles_a_chunked_body_and_closes_it():
    response = _Response(200, body=b"<html>caf\xc3\xa9</html>")
    assert http_client.read_text(response) == "<html>café</html>"
    assert response.closed


def test_read_text_rejects_a_body_over_the_size_cap():
    response = _Response(200, body=b"x" * 100)
    try:
        http_client.read_text(response, max_bytes=50)
    except http_client.ResponseTooLarge:
        pass
    else:
        raise AssertionError("expected ResponseTooLarge")
    assert response.closed


def test_response_too_large_is_a_handled_http_exception():
    # search_adapter and the search workers catch HTTP_EXCEPTIONS; an oversized
    # body must be a skipped site, not a crashed worker.
    assert issubclass(http_client.ResponseTooLarge, http_client.HTTP_EXCEPTIONS)


def test_ytdlp_impersonate_target_translates_configured_profiles(monkeypatch):
    monkeypatch.setattr(http_client, "HAS_CURL_CFFI", True)
    assert http_client.ytdlp_impersonate_target("chrome131") == "chrome-131"
    assert http_client.ytdlp_impersonate_target("safari184") == "safari-18.4"


def test_ytdlp_impersonate_target_falls_back_to_the_bare_client(monkeypatch):
    """An unmapped profile still gets a browser fingerprint: yt-dlp resolves a
    bare client name to whichever version it has available."""
    monkeypatch.setattr(http_client, "HAS_CURL_CFFI", True)
    assert http_client.ytdlp_impersonate_target("firefox141") == "firefox"


def test_ytdlp_impersonate_target_is_none_without_curl_cffi(monkeypatch):
    monkeypatch.setattr(http_client, "HAS_CURL_CFFI", False)
    assert http_client.ytdlp_impersonate_target("chrome131") is None


def test_request_headers_sets_user_agent_without_curl_cffi(monkeypatch):
    monkeypatch.setattr(http_client, "HAS_CURL_CFFI", False)
    assert "User-Agent" in http_client.request_headers()


def test_request_headers_leaves_impersonation_profile_alone(monkeypatch):
    monkeypatch.setattr(http_client, "HAS_CURL_CFFI", True)
    assert http_client.request_headers() == {}

