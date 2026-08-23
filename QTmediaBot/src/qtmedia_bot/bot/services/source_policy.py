"""URL and network safety checks for bot-originated source inspection."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit


class SourcePolicyError(ValueError):
    """A source URL failed a bot safety or support policy check."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _allowed_host(host: str, allowed_domains: frozenset[str]) -> bool:
    normalized_host = host.casefold().rstrip(".").removeprefix("www.")
    return any(
        normalized_host == domain
        or normalized_host.endswith(f".{domain}")
        for domain in allowed_domains
    )


def _public_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_global


def _resolved_addresses(
    host: str,
    resolve_host: Callable[..., Iterable[tuple]],
) -> tuple[str, ...]:
    try:
        records = resolve_host(host, None, type=socket.SOCK_STREAM)
        addresses = tuple(record[4][0] for record in records if record[4])
    except (OSError, socket.gaierror, TimeoutError) as exc:
        raise SourcePolicyError(
            "source_unresolvable", "The source host could not be resolved."
        ) from exc
    if not addresses:
        raise SourcePolicyError(
            "source_unresolvable", "The source host could not be resolved."
        )
    return addresses


def validate_source_url(
    url: str,
    allowed_domains: frozenset[str],
    resolve_host: Callable[..., Iterable[tuple]] = socket.getaddrinfo,
) -> None:
    """Validate a source URL before any downloader or network fetch runs."""

    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https":
        raise SourcePolicyError("https_required", "Only HTTPS source links are supported.")
    if not parsed.hostname:
        raise SourcePolicyError("invalid_url", "The source link is invalid.")
    if parsed.username or parsed.password:
        raise SourcePolicyError(
            "credentials_not_allowed", "Source links with embedded credentials are not supported."
        )
    if not allowed_domains or not _allowed_host(parsed.hostname, allowed_domains):
        raise SourcePolicyError(
            "unsupported_domain", "This source is not supported by the bot."
        )

    try:
        literal_address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        addresses = _resolved_addresses(parsed.hostname, resolve_host)
    else:
        addresses = (str(literal_address),)

    if not all(_public_address(address) for address in addresses):
        raise SourcePolicyError(
            "private_network", "The source resolves to a restricted network."
        )
