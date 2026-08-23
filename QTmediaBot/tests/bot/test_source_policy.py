import socket

import pytest

from qtmedia_bot.bot.services.source_policy import (
    SourcePolicyError,
    validate_source_url,
)


def resolver_for(address: str):
    def resolve(host, _port, type=0):
        del host, type
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    return resolve


def test_policy_rejects_non_https_and_empty_allowlist():
    with pytest.raises(SourcePolicyError, match="HTTPS"):
        validate_source_url(
            "http://example.com/video", frozenset({"example.com"}), resolver_for("93.184.216.34")
        )

    with pytest.raises(SourcePolicyError, match="supported"):
        validate_source_url(
            "https://example.com/video", frozenset(), resolver_for("93.184.216.34")
        )


def test_policy_rejects_disallowed_hosts_and_credentials():
    with pytest.raises(SourcePolicyError, match="supported"):
        validate_source_url(
            "https://other.example/video",
            frozenset({"example.com"}),
            resolver_for("93.184.216.34"),
        )

    with pytest.raises(SourcePolicyError, match="credentials"):
        validate_source_url(
            "https://user:password@example.com/video",
            frozenset({"example.com"}),
            resolver_for("93.184.216.34"),
        )


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "::1"])
def test_policy_rejects_non_public_resolved_addresses(address):
    with pytest.raises(SourcePolicyError, match="network"):
        validate_source_url(
            "https://media.example.com/video",
            frozenset({"example.com"}),
            resolver_for(address),
        )


def test_policy_accepts_allowed_subdomain_with_public_address():
    validate_source_url(
        "https://media.example.com/video",
        frozenset({"example.com"}),
        resolver_for("93.184.216.34"),
    )

