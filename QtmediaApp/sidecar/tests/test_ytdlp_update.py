"""yt-dlp update: signature verification against the real release files,
install and activation with synthetic archives (no network)."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from qtmedia_engine import ytdlp_update as update
from qtmedia_engine.engine import Engine
from qtmedia_engine.protocol import ProtocolError, Request, parse_request
from qtmedia_engine.ytdlp_update import Status, UpdateError

FIXTURES = Path(__file__).parent / "fixtures" / "ytdlp"
# The 2026.08.19 stable release's SHA2-256SUMS and its signature.
SUMS = (FIXTURES / "SHA2-256SUMS").read_bytes()
SIGNATURE = (FIXTURES / "SHA2-256SUMS.sig").read_bytes()
RELEASE_HASH = "1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6"


def test_pinned_key_matches_its_fingerprint():
    assert update.key_fingerprint() == update.KEY_FINGERPRINT


def test_real_release_signature_verifies():
    assert update.verify_signature(SUMS, SIGNATURE)
    assert update.signed_hash(SUMS, SIGNATURE) == RELEASE_HASH


@pytest.mark.parametrize(
    "sums, signature",
    [
        (SUMS.replace(b"1fa6", b"1fa7"), SIGNATURE),  # tampered document
        (SUMS, SIGNATURE[:-1] + bytes([SIGNATURE[-1] ^ 1])),  # tampered signature
        (SUMS, SIGNATURE[:40]),  # truncated
        (SUMS, b""),
        (SUMS, b"not a signature"),
    ],
)
def test_bad_signatures_are_rejected(sums: bytes, signature: bytes):
    assert not update.verify_signature(sums, signature)
    with pytest.raises(UpdateError, match="update_verification_failed"):
        update.signed_hash(sums, signature)


def test_version_ordering():
    assert update.version_key("2026.09.27.232945") > update.version_key("2026.08.19")
    assert update.version_key("2026.08.19") > update.version_key("2026.07.04")
    assert update.version_key("garbage") == ()


def archive(version: str) -> bytes:
    """A minimal importable yt-dlp zipimport file with a shebang prefix."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("yt_dlp/__init__.py", "")
        bundle.writestr("yt_dlp/version.py", f"__version__ = '{version}'\n")
    return b"#!/usr/bin/env python3\n" + buffer.getvalue()


class FakeRelease:
    """GitHub API + assets for one release, signed by a stand-in check."""

    def __init__(self, tag: str, payload: bytes, *, listed_hash: str | None = None):
        self.tag = tag
        self.payload = payload
        digest = listed_hash or hashlib.sha256(payload).hexdigest()
        self.sums = f"{digest}  yt-dlp\n".encode()
        self.requests: list[str] = []

    def fetch(self, url: str, limit: int) -> bytes:
        self.requests.append(url)
        if url.endswith("/releases/latest"):
            repo = url.removeprefix("https://api.github.com/repos/").removesuffix(
                "/releases/latest"
            )
            base = f"https://github.com/{repo}/releases/download/{self.tag}/"
            return json.dumps(
                {
                    "tag_name": self.tag,
                    "assets": [
                        {"name": name, "browser_download_url": base + name}
                        for name in ("yt-dlp", "SHA2-256SUMS", "SHA2-256SUMS.sig", "yt-dlp.exe")
                    ],
                }
            ).encode()
        name = url.rsplit("/", 1)[1]
        return {"yt-dlp": self.payload, "SHA2-256SUMS": self.sums, "SHA2-256SUMS.sig": b"sig"}[name]


@pytest.fixture
def trust_fake_signature(monkeypatch):
    monkeypatch.setattr(update, "verify_signature", lambda sums, signature: signature == b"sig")


@pytest.fixture
def restore_ytdlp():
    """Activation edits sys.path and sys.modules; put the real yt-dlp back."""
    path = list(sys.path)
    yield
    sys.path[:] = path
    update._purge_ytdlp_modules()


def test_install_verifies_and_activates_a_newer_release(
    tmp_path: Path, trust_fake_signature, restore_ytdlp
):
    release = FakeRelease("2099.01.02.123456", archive("2099.01.02.123456"))
    installed = update.install_update(tmp_path, "nightly", "2026.08.19", release.fetch)
    assert installed == "2099.01.02.123456"
    assert release.requests[0] == (
        "https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest"
    )
    assert update.read_installed(tmp_path).version == "2099.01.02.123456"

    status = update.activate(tmp_path)
    assert status == Status(version="2099.01.02.123456", source="updated", channel="nightly")
    from yt_dlp.version import __version__

    assert __version__ == "2099.01.02.123456"


def test_install_reports_current_when_nothing_is_newer(tmp_path: Path, trust_fake_signature):
    release = FakeRelease("2026.08.19", archive("2026.08.19"))
    assert update.install_update(tmp_path, "stable", "2026.08.19", release.fetch) is None
    assert len(release.requests) == 1
    assert not (tmp_path / "current").exists()


def test_install_rejects_an_archive_that_does_not_match_the_signed_sum(
    tmp_path: Path, trust_fake_signature
):
    release = FakeRelease("2099.01.01", archive("2099.01.01"), listed_hash="0" * 64)
    with pytest.raises(UpdateError, match="update_verification_failed"):
        update.install_update(tmp_path, "stable", "2026.08.19", release.fetch)
    assert not (tmp_path / "current").exists()


def test_install_rejects_an_unsigned_release(tmp_path: Path):
    release = FakeRelease("2099.01.01", archive("2099.01.01"))
    with pytest.raises(UpdateError, match="update_verification_failed"):
        update.install_update(tmp_path, "stable", "2026.08.19", release.fetch)


def test_install_rejects_an_archive_whose_version_differs_from_the_tag(
    tmp_path: Path, trust_fake_signature
):
    release = FakeRelease("2099.01.01", archive("2001.01.01"))
    with pytest.raises(UpdateError, match="update_verification_failed"):
        update.install_update(tmp_path, "stable", "2026.08.19", release.fetch)
    assert not (tmp_path / "current").exists()


def test_a_tampered_install_is_ignored_at_start(
    tmp_path: Path, trust_fake_signature, restore_ytdlp
):
    release = FakeRelease("2099.01.01", archive("2099.01.01"))
    update.install_update(tmp_path, "stable", "2026.08.19", release.fetch)
    (tmp_path / "current" / "yt-dlp").write_bytes(archive("2099.01.01") + b"x")
    assert update.read_installed(tmp_path) is None
    assert update.activate(tmp_path).source == "bundled"


def test_an_older_update_never_replaces_a_newer_bundled_copy(
    tmp_path: Path, trust_fake_signature, restore_ytdlp
):
    release = FakeRelease("2000.01.01", archive("2000.01.01"))
    update.install_update(tmp_path, "stable", "1999.01.01", release.fetch)
    status = update.activate(tmp_path)
    assert status.source == "bundled"
    assert status.version == update.bundled_version()


def test_no_tools_dir_uses_the_bundled_copy(restore_ytdlp):
    assert update.activate(None).source == "bundled"


def test_release_assets_must_come_from_the_channel_repository():
    def fetch(url: str, limit: int) -> bytes:
        return json.dumps(
            {
                "tag_name": "2099.01.01",
                "assets": [
                    {"name": name, "browser_download_url": f"https://evil.invalid/{name}"}
                    for name in ("yt-dlp", "SHA2-256SUMS", "SHA2-256SUMS.sig")
                ],
            }
        ).encode()

    with pytest.raises(UpdateError, match="update_unavailable"):
        update.latest_release("stable", fetch)


def test_protocol_accepts_only_known_channels():
    request = parse_request('{"id":"u","action":"ytdlp_update","channel":"nightly"}')
    assert request.payload == {"channel": "nightly"}
    for line in (
        '{"id":"u","action":"ytdlp_update","channel":"master"}',
        '{"id":"u","action":"ytdlp_update"}',
        '{"id":"u","action":"ytdlp_status","channel":"stable"}',
    ):
        with pytest.raises(ProtocolError):
            parse_request(line)


def test_engine_reports_status_and_update_results(tmp_path: Path):
    events: list[dict[str, object]] = []
    calls: list[tuple[Path, str, str]] = []

    def updater(tools_dir: Path, channel: str, current: str) -> str | None:
        calls.append((tools_dir, channel, current))
        if channel == "stable":
            return None
        raise UpdateError("update_verification_failed")

    engine = Engine(
        tmp_path / "library",
        emit=events.append,
        ytdlp=Status(version="2026.08.19", source="bundled"),
        tools_dir=tmp_path / "tools",
        updater=updater,
    )
    engine.handle(Request("s", "ytdlp_status", {}))
    engine.handle(Request("u1", "ytdlp_update", {"channel": "stable"}))
    engine.handle(Request("u2", "ytdlp_update", {"channel": "nightly"}))

    assert events == [
        {"id": "s", "event": "ytdlp_status", "version": "2026.08.19", "source": "bundled", "channel": None},
        {"id": "u1", "event": "ytdlp_updated", "status": "current", "version": "2026.08.19", "channel": "stable"},
        {"id": "u2", "event": "error", "code": "update_verification_failed"},
    ]
    assert calls[0] == (tmp_path / "tools", "stable", "2026.08.19")


def test_engine_without_a_tools_dir_cannot_update(tmp_path: Path):
    events: list[dict[str, object]] = []
    engine = Engine(tmp_path, emit=events.append)
    engine.handle(Request("u", "ytdlp_update", {"channel": "stable"}))
    assert events == [{"id": "u", "event": "error", "code": "update_unavailable"}]
