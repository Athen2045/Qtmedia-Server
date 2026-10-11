from __future__ import annotations

import socket
import struct

import pytest

from qtmedia.desktop_service import network


def _answer(query: bytes, addresses: list[str], ttl: int = 120) -> bytes:
    """Build a DoH wire-format response that answers ``query`` with A records."""
    header = query[:2] + struct.pack(">HHHHH", 0x8180, 1, len(addresses), 0, 0)
    body = query[12:]
    for address in addresses:
        # Name as a compression pointer to the question at offset 12.
        body += struct.pack(">HHHIH", 0xC00C, 1, 1, ttl, 4) + socket.inet_aton(address)
    return header + body


def test_doh_query_round_trips_a_records():
    query = network.encode_query("xhamster.com", query_id=0x1234)

    assert query[:2] == b"\x12\x34"
    assert b"\x08xhamster\x03com\x00" in query
    assert network.decode_addresses(_answer(query, ["104.16.4.81", "104.16.3.81"])) == (
        ["104.16.4.81", "104.16.3.81"],
        120,
    )


def test_resolver_caches_answers_and_rejects_non_https_endpoints():
    calls: list[str] = []

    def fetch(url: str, query: bytes) -> bytes:
        calls.append(url)
        return _answer(query, ["104.19.239.156"])

    resolver = network.DohResolver("https://1.1.1.1/dns-query", fetch=fetch, clock=lambda: 0.0)

    assert resolver.resolve("spankbang.com") == ["104.19.239.156"]
    assert resolver.resolve("SpankBang.com.") == ["104.19.239.156"]
    assert calls == ["https://1.1.1.1/dns-query"]
    with pytest.raises(ValueError):
        network.DohResolver("http://1.1.1.1/dns-query")


def test_patched_getaddrinfo_uses_doh_for_names_and_system_for_literals(monkeypatch):
    seen: list[object] = []

    def system(host, port, family=0, type=0, proto=0, flags=0):
        seen.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]

    resolver = network.DohResolver(
        "https://1.1.1.1/dns-query",
        fetch=lambda _url, query: _answer(query, ["104.16.4.81"]),
    )
    getaddrinfo = network.doh_getaddrinfo(resolver, system)

    assert getaddrinfo("xhamster.com", 443)[0][4] == ("104.16.4.81", 443)
    assert getaddrinfo("127.0.0.1", 80)[0][4] == ("127.0.0.1", 80)
    assert seen == ["104.16.4.81", "127.0.0.1"]


def test_patched_getaddrinfo_falls_back_to_system_dns_when_doh_fails():
    def failing(_url, _query):
        raise OSError("unreachable")

    getaddrinfo = network.doh_getaddrinfo(
        network.DohResolver("https://1.1.1.1/dns-query", fetch=failing),
        lambda host, port, *_rest: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", port))],
    )

    assert getaddrinfo("example.com", 443)[0][4] == ("192.0.2.1", 443)


def test_curl_handles_get_the_doh_url_on_every_request():
    class FakeCurl:
        def __init__(self):
            self.options: dict[object, object] = {}
            self.performed = 0

        def setopt(self, option, value):
            self.options[option] = value

        def perform(self, clear_headers=True, clear_resolve=True):
            self.performed += 1

    network.patch_curl_perform(FakeCurl, "https://1.1.1.1/dns-query", doh_option="DOH_URL")
    curl = FakeCurl()
    curl.perform()
    curl.options.clear()  # curl_cffi resets handles between requests
    curl.perform()

    assert curl.performed == 2
    assert curl.options == {"DOH_URL": b"https://1.1.1.1/dns-query"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("socks5h://127.0.0.1:1080", {"proxy": "socks5h://127.0.0.1:1080"}),
        ("http://user:secret@proxy.example:8080", {"proxy": "http://user:secret@proxy.example:8080"}),
        ("", {}),
        ("ftp://proxy.example:21", {}),
        ("socks5://", {}),
    ],
)
def test_proxy_options_accept_only_supported_proxy_urls(monkeypatch, value, expected):
    monkeypatch.setenv("QTMEDIA_PROXY", value)

    assert network.proxy_options() == expected


def test_new_session_routes_through_the_configured_proxy(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.proxies: dict[str, str] = {}

    monkeypatch.setenv("QTMEDIA_PROXY", "socks5h://127.0.0.1:1080")
    monkeypatch.setattr(network.http_client, "new_session", lambda _profile=None: FakeSession())

    session = network.new_session(None)

    assert session.proxies == {"http": "socks5h://127.0.0.1:1080", "https": "socks5h://127.0.0.1:1080"}


def test_inspection_and_download_options_carry_the_proxy(monkeypatch, tmp_path):
    import threading

    from qtmedia.desktop_service import inspection
    from qtmedia.desktop_service.download import build_download_options
    from qtmedia.desktop_service.models import (
        FormatOption,
        InspectedMedia,
        MediaLibrary,
    )

    monkeypatch.setenv("QTMEDIA_PROXY", "socks5h://127.0.0.1:1080")
    media = InspectedMedia(
        source_url="https://www.eporner.com/video-abc/title/",
        media_id="media-1",
        title="Example",
        site="Eporner",
        thumbnail_url=None,
        formats=(FormatOption("video", "Video", "mp4"),),
    )
    library = MediaLibrary.create(tmp_path / "library")

    download = build_download_options(media, "video", library, lambda _event: None, threading.Event())

    assert download["proxy"] == "socks5h://127.0.0.1:1080"
    assert inspection._desktop_ydl_options(media.source_url)["proxy"] == "socks5h://127.0.0.1:1080"
