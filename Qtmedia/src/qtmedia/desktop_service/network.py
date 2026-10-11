"""Desktop network routing: DNS-over-HTTPS and an optional proxy.

Some networks hijack DNS for supported sites or block them outright. The host
passes the user's choices to the engine through ``QTMEDIA_DOH`` (an RFC 8484
endpoint) and ``QTMEDIA_PROXY``. DoH covers both Python sockets (requests,
urllib) and curl_cffi, which resolves names inside libcurl.
"""

from __future__ import annotations

import base64
import ipaddress
import os
import secrets
import socket
import struct
import threading
import time
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit

from ..net import http_client

DOH_ENV = "QTMEDIA_DOH"
PROXY_ENV = "QTMEDIA_PROXY"
PROXY_SCHEMES = frozenset({"http", "https", "socks4", "socks4a", "socks5", "socks5h"})
DOH_TIMEOUT_SECONDS = 5
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 300
TYPE_A = 1

Fetch = Callable[[str, bytes], bytes]
GetAddrInfo = Callable[..., list]


def configured_proxy() -> str | None:
    value = os.getenv(PROXY_ENV, "").strip()
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return None
    if parsed.scheme.casefold() not in PROXY_SCHEMES or not parsed.hostname:
        return None
    return value


def configured_doh() -> str | None:
    value = os.getenv(DOH_ENV, "").strip()
    return value if value and urlsplit(value).scheme == "https" else None


def proxy_options() -> dict[str, object]:
    """yt-dlp options for the configured proxy."""
    proxy = configured_proxy()
    return {"proxy": proxy} if proxy else {}


def apply_proxy(session):
    """Route a requests/curl_cffi session through the configured proxy."""
    proxy = configured_proxy()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def new_session(impersonate: str | None):
    """An HTTP session for engine-side requests that honours the proxy."""
    return apply_proxy(http_client.new_session(impersonate))


def encode_query(host: str, *, query_id: int | None = None, record_type: int = TYPE_A) -> bytes:
    identifier = secrets.randbelow(0x10000) if query_id is None else query_id
    header = struct.pack(">HHHHHH", identifier, 0x0100, 1, 0, 0, 0)
    name = b"".join(
        bytes([len(label)]) + label for label in host.encode("idna").split(b".") if label
    )
    return header + name + b"\x00" + struct.pack(">HH", record_type, 1)


def _skip_name(payload: bytes, offset: int) -> int:
    while True:
        length = payload[offset]
        if length & 0xC0 == 0xC0:  # compression pointer ends the name
            return offset + 2
        offset += 1
        if length == 0:
            return offset
        offset += length


def decode_addresses(payload: bytes) -> tuple[list[str], int]:
    """Return the IPv4 answers and their smallest TTL from a DNS response."""
    _identifier, flags, questions, answers, _ns, _ar = struct.unpack(">HHHHHH", payload[:12])
    if flags & 0x000F:  # non-zero RCODE
        return [], MIN_TTL_SECONDS
    offset = 12
    for _ in range(questions):
        offset = _skip_name(payload, offset) + 4
    addresses: list[str] = []
    ttl = MAX_TTL_SECONDS
    for _ in range(answers):
        offset = _skip_name(payload, offset)
        record_type, _record_class, record_ttl, length = struct.unpack(
            ">HHIH", payload[offset : offset + 10]
        )
        offset += 10
        if record_type == TYPE_A and length == 4:
            addresses.append(socket.inet_ntoa(payload[offset : offset + 4]))
            ttl = min(ttl, record_ttl)
        offset += length
    return addresses, ttl


def _https_fetch(url: str, query: bytes) -> bytes:
    encoded = base64.urlsafe_b64encode(query).rstrip(b"=").decode("ascii")
    request = urllib.request.Request(
        f"{url}?dns={encoded}", headers={"Accept": "application/dns-message"}
    )
    # Never through the proxy: DoH exists for networks whose resolver lies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=DOH_TIMEOUT_SECONDS) as response:
        return response.read(64 * 1024)


class DohResolver:
    def __init__(
        self,
        url: str,
        *,
        fetch: Fetch = _https_fetch,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if urlsplit(url).scheme != "https":
            raise ValueError("doh_requires_https")
        self.url = url
        self._fetch = fetch
        self._clock = clock
        self._cache: dict[str, tuple[float, list[str]]] = {}
        self._lock = threading.Lock()

    def resolve(self, host: str) -> list[str]:
        name = host.casefold().rstrip(".")
        now = self._clock()
        with self._lock:
            cached = self._cache.get(name)
            if cached and cached[0] > now:
                return list(cached[1])
        addresses, ttl = decode_addresses(self._fetch(self.url, encode_query(name)))
        if addresses:
            expiry = now + max(MIN_TTL_SECONDS, min(ttl, MAX_TTL_SECONDS))
            with self._lock:
                self._cache[name] = (expiry, addresses)
        return addresses


def _is_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def doh_getaddrinfo(resolver: DohResolver, system: GetAddrInfo) -> GetAddrInfo:
    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        name = host.decode("ascii") if isinstance(host, bytes) else host
        if (
            not name
            or _is_literal(name)
            or name.casefold() == "localhost"
            or family == socket.AF_INET6
        ):
            return system(host, port, family, type, proto, flags)
        try:
            addresses = resolver.resolve(name)
        except Exception:  # noqa: BLE001 - fall back to the system resolver
            addresses = []
        if not addresses:
            return system(host, port, family, type, proto, flags)
        results: list = []
        for address in addresses:
            results.extend(system(address, port, socket.AF_INET, type, proto, flags))
        return results

    return getaddrinfo


def patch_curl_perform(curl_class: type, doh_url: str, *, doh_option: object) -> None:
    """Set the DoH URL on every transfer; curl_cffi resets handles between requests."""
    original = curl_class.perform
    encoded = doh_url.encode("ascii")

    def perform(self, *args, **kwargs):
        self.setopt(doh_option, encoded)
        return original(self, *args, **kwargs)

    curl_class.perform = perform


_installed = False


def install_from_env() -> None:
    """Route this process's name lookups through the configured DoH endpoint."""
    global _installed
    doh_url = configured_doh()
    if _installed or not doh_url:
        return
    socket.getaddrinfo = doh_getaddrinfo(DohResolver(doh_url), socket.getaddrinfo)
    try:
        from curl_cffi import Curl, CurlOpt  # pylint: disable=import-outside-toplevel
    except ImportError:
        pass
    else:
        patch_curl_perform(Curl, doh_url, doh_option=CurlOpt.DOH_URL)
    _installed = True
