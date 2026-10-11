"""User-triggered yt-dlp updates for the frozen engine.

The engine ships with a pinned yt-dlp, but sites (YouTube above all) change
every few weeks. Settings → "Update yt-dlp" downloads the official
platform-independent ``yt-dlp`` zipimport release (it bundles yt-dlp-ejs)
from GitHub and keeps it in the app's data folder. Every install and every
start re-checks it:

1. ``SHA2-256SUMS.sig`` is a valid OpenPGP signature over ``SHA2-256SUMS`` by
   the yt-dlp signing key pinned below (RSA-4096, fingerprint
   ``AC0C BBE6 848D 6A87 3464 AF4E 57CF 6593 3B5A 7581``);
2. the ``yt-dlp`` file's SHA-256 matches its line in the signed sums.

At start, :func:`activate` puts a verified update ahead of the bundled copy
on ``sys.path`` only when it is newer, so an app upgrade with a newer bundled
yt-dlp wins over an old download. Updates apply on the next engine start.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

TOOLS_DIR_ENV = "QTMEDIA_YTDLP_DIR"

KEY_FINGERPRINT = bytes.fromhex("AC0CBBE6848D6A873464AF4E57CF65933B5A7581")
KEY_CREATED = 1677455406
KEY_EXPONENT = 65537
KEY_MODULUS = int(
    "f4ac5f738c63c0b74b6196de42d5e6f371c0155fb35bd6ff9ea908e4f9611975"
    "31135428375803399e002b947766fdf66acd480efa9018ac1eb418a7a0edf7d4"
    "0dff92d1714a11975e44b61e01aaaa2a14a26d56a50e3bce04ecedbb75bad3b1"
    "cb113400a80ef04cfb88b765aa9a92fad0d21ccabdbb2f1aa681d37798dbd9da"
    "22cef9b3f49ca47f0be3e013d1f8cadcb00dad76cccc7a3e66429d538e3aee97"
    "644166754c71750f5f143a9df4b701298d8b0ce712628d6c698d185a26561edc"
    "d5a19bb590ece39d2e458eaff204724b2260c7ee93711e6eecfcf9dababa6640"
    "5b4316bba4b7eda58439e9294986aff23fdc81ea1ff5fef673e84b8ba2a90e47"
    "a5b941f012bee167e96a2120ef92e7bee38f7d920f298c976bfd00ed0a233308"
    "0eac3f3ca334fe54290a92427e8a35d9ee01cd8e670169474a2bb7c320439823"
    "adcbc9ce905a41904e28057df4945d61c308ef5a5cd84fdde8ea15680632d094"
    "b2b6e4709916b9663bab9011cbfd391db48cdcae0353d7aab67c66895d5643c9"
    "d7b88f49809411be1e4f4e49f2e4bb71ab3726aaf58ef538c705baecd7804f10"
    "ef5f717c4a2ff08505bcd70d2bef02002b76aaa53289dc43fca271395f2faab3"
    "27c10a162a96d7840c4dd027e92bae653a1d5c24e2227c284fb5a38ee14f28a7"
    "6f7c7d463f86e7a9dcd39f32f10920c812d7f27cfb085fef4623b26493fcd98d",
    16,
)

CHANNELS = {
    "stable": "yt-dlp/yt-dlp",
    "nightly": "yt-dlp/yt-dlp-nightly-builds",
}
ASSET = "yt-dlp"
SUMS = "SHA2-256SUMS"
SIGNATURE = "SHA2-256SUMS.sig"
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_SMALL_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 30

# ASN.1 DigestInfo prefixes for EMSA-PKCS1-v1_5 (RFC 8017 §9.2).
_DIGESTS = {
    8: ("sha256", bytes.fromhex("3031300d060960864801650304020105000420")),
    10: ("sha512", bytes.fromhex("3051300d060960864801650304020305000440")),
}


class UpdateError(Exception):
    """A stable error code for the UI."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------
# OpenPGP signature verification (v4, RSA, binary document)


def key_fingerprint(modulus: int = KEY_MODULUS, exponent: int = KEY_EXPONENT) -> bytes:
    """The v4 fingerprint (RFC 4880 §12.2) of an RSA public key."""

    def mpi(value: int) -> bytes:
        return value.bit_length().to_bytes(2, "big") + value.to_bytes(
            (value.bit_length() + 7) // 8, "big"
        )

    body = bytes([4]) + KEY_CREATED.to_bytes(4, "big") + bytes([1]) + mpi(modulus) + mpi(exponent)
    return hashlib.sha1(b"\x99" + len(body).to_bytes(2, "big") + body).digest()


def _packet_body(data: bytes) -> bytes:
    """The body of the first OpenPGP packet (old or new format header)."""
    if len(data) < 2 or not data[0] & 0x80:
        raise UpdateError("update_verification_failed")
    if data[0] & 0x40:  # new format
        tag, first = data[0] & 0x3F, data[1]
        if first < 192:
            start, length = 2, first
        elif first < 224:
            start, length = 3, ((first - 192) << 8) + data[2] + 192
        elif first == 255:
            start, length = 6, int.from_bytes(data[2:6], "big")
        else:
            raise UpdateError("update_verification_failed")
    else:
        tag, kind = (data[0] >> 2) & 0x0F, data[0] & 0x03
        sizes = {0: 1, 1: 2, 2: 4}
        if kind not in sizes:
            raise UpdateError("update_verification_failed")
        start = 1 + sizes[kind]
        length = int.from_bytes(data[1:start], "big")
    if tag != 2 or len(data) < start + length:
        raise UpdateError("update_verification_failed")
    return data[start : start + length]


def _subpackets(area: bytes) -> list[tuple[int, bytes]]:
    found = []
    index = 0
    while index < len(area):
        first = area[index]
        if first < 192:
            length, index = first, index + 1
        elif first < 255:
            length, index = ((first - 192) << 8) + area[index + 1] + 192, index + 2
        else:
            length, index = int.from_bytes(area[index + 1 : index + 5], "big"), index + 5
        if length < 1 or index + length > len(area):
            raise UpdateError("update_verification_failed")
        found.append((area[index] & 0x7F, area[index + 1 : index + length]))
        index += length
    return found


def verify_signature(document: bytes, signature: bytes) -> bool:
    """Whether ``signature`` is the pinned key's signature over ``document``."""
    try:
        body = _packet_body(signature)
        version, sig_type, key_algo, hash_algo = body[0], body[1], body[2], body[3]
        if (version, sig_type, key_algo) != (4, 0x00, 1) or hash_algo not in _DIGESTS:
            return False
        hashed_length = int.from_bytes(body[4:6], "big")
        hashed_end = 6 + hashed_length
        hashed = body[6:hashed_end]
        unhashed_length = int.from_bytes(body[hashed_end : hashed_end + 2], "big")
        cursor = hashed_end + 2 + unhashed_length
        cursor += 2  # left 16 bits of the digest
        bits = int.from_bytes(body[cursor : cursor + 2], "big")
        value = int.from_bytes(body[cursor + 2 : cursor + 2 + (bits + 7) // 8], "big")
    except (IndexError, UpdateError):
        return False

    try:
        issuers = [data for kind, data in _subpackets(hashed) if kind == 33]
    except (IndexError, UpdateError):
        return False
    if any(issuer[1:] != KEY_FINGERPRINT for issuer in issuers):
        return False

    name, prefix = _DIGESTS[hash_algo]
    digest = hashlib.new(name)
    digest.update(document)
    digest.update(body[:hashed_end])
    digest.update(b"\x04\xff" + hashed_end.to_bytes(4, "big"))
    expected_hash = digest.digest()

    size = (KEY_MODULUS.bit_length() + 7) // 8
    if value >= KEY_MODULUS:
        return False
    decoded = pow(value, KEY_EXPONENT, KEY_MODULUS).to_bytes(size, "big")
    info = prefix + expected_hash
    padded = b"\x00\x01" + b"\xff" * (size - len(info) - 3) + b"\x00" + info
    return decoded == padded


def signed_hash(sums: bytes, signature: bytes, name: str = ASSET) -> str:
    """The SHA-256 the signed ``SHA2-256SUMS`` lists for ``name``."""
    if not verify_signature(sums, signature):
        raise UpdateError("update_verification_failed")
    for line in sums.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    raise UpdateError("update_verification_failed")


# --------------------------------------------------------------------------
# Versions and the installed update


def version_key(version: str) -> tuple[int, ...]:
    """``2026.08.19`` / ``2026.09.27.232945`` → comparable integers."""
    try:
        return tuple(int(part) for part in version.strip().split("."))
    except ValueError:
        return ()


@dataclass(frozen=True)
class Installed:
    version: str
    channel: str
    path: Path


def _current_dir(tools_dir: Path) -> Path:
    return tools_dir / "current"


def read_installed(tools_dir: Path) -> Installed | None:
    """The installed update, if it still verifies."""
    folder = _current_dir(tools_dir)
    try:
        meta = json.loads((folder / "version.json").read_text(encoding="utf-8"))
        sums = (folder / SUMS).read_bytes()
        signature = (folder / SIGNATURE).read_bytes()
        archive = folder / ASSET
        expected = signed_hash(sums, signature)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            return None
        version, channel = str(meta["version"]), str(meta["channel"])
    except (OSError, ValueError, KeyError, TypeError, UpdateError):
        return None
    if not version_key(version) or channel not in CHANNELS:
        return None
    return Installed(version=version, channel=channel, path=archive)


def _purge_ytdlp_modules() -> None:
    for name in [name for name in sys.modules if name.split(".")[0] in {"yt_dlp", "yt_dlp_ejs"}]:
        del sys.modules[name]


def bundled_version() -> str:
    """The yt-dlp version shipped with the engine (imported, then forgotten so
    an update can still take its place)."""
    from yt_dlp.version import __version__  # pylint: disable=import-outside-toplevel

    _purge_ytdlp_modules()
    return str(__version__)


@dataclass(frozen=True)
class Status:
    version: str
    source: str  # "bundled" | "updated"
    channel: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"version": self.version, "source": self.source, "channel": self.channel}


def activate(tools_dir: Path | None) -> Status:
    """Uses a verified, newer installed update in place of the bundled yt-dlp.

    Must run before anything imports ``yt_dlp``.
    """
    bundled = bundled_version()
    installed = read_installed(tools_dir) if tools_dir else None
    if installed is None or version_key(installed.version) <= version_key(bundled):
        return Status(version=bundled, source="bundled")
    path = str(installed.path)
    sys.path.insert(0, path)
    try:
        from yt_dlp.version import (
            __version__,  # pylint: disable=import-outside-toplevel
        )

        if str(__version__) != installed.version:
            raise ImportError("version mismatch")
    except Exception:  # noqa: BLE001 - a broken update must never stop the engine
        sys.path.remove(path)
        _purge_ytdlp_modules()
        return Status(version=bundled, source="bundled")
    return Status(version=installed.version, source="updated", channel=installed.channel)


def tools_dir_from_env() -> Path | None:
    value = os.getenv(TOOLS_DIR_ENV, "").strip()
    return Path(value) if value else None


# --------------------------------------------------------------------------
# Downloading an update

Fetch = Callable[[str, int], bytes]


def _opener() -> urllib.request.OpenerDirector:
    from qtmedia.desktop_service.network import (  # pylint: disable=import-outside-toplevel
        configured_proxy,
    )

    proxy = configured_proxy()
    handlers = []
    if proxy and proxy.split(":", 1)[0].casefold() in {"http", "https"}:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def http_fetch(url: str, limit: int) -> bytes:
    """GET over HTTPS with a size limit (the configured HTTP proxy is used;
    DNS-over-HTTPS applies through the engine's resolver hook)."""
    if not url.startswith("https://"):
        raise UpdateError("update_unavailable")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Qtmedia", "Accept": "application/octet-stream, application/json"},
    )
    try:
        with _opener().open(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(limit + 1)
    except OSError as error:
        raise UpdateError("update_unavailable") from error
    if len(data) > limit:
        raise UpdateError("update_unavailable")
    return data


def latest_release(channel: str, fetch: Fetch = http_fetch) -> tuple[str, dict[str, str]]:
    """The newest release tag on ``channel`` and its asset download URLs."""
    repository = CHANNELS.get(channel)
    if repository is None:
        raise UpdateError("invalid_request")
    raw = fetch(f"https://api.github.com/repos/{repository}/releases/latest", MAX_SMALL_BYTES)
    try:
        release = json.loads(raw)
        tag = str(release["tag_name"])
        assets = {
            str(asset["name"]): str(asset["browser_download_url"])
            for asset in release["assets"]
            if asset.get("name") in {ASSET, SUMS, SIGNATURE}
        }
    except (ValueError, KeyError, TypeError) as error:
        raise UpdateError("update_unavailable") from error
    prefix = f"https://github.com/{repository}/releases/download/"
    if (
        not version_key(tag)
        or set(assets) != {ASSET, SUMS, SIGNATURE}
        or not all(url.startswith(prefix) for url in assets.values())
    ):
        raise UpdateError("update_unavailable")
    return tag, assets


def install_update(
    tools_dir: Path,
    channel: str,
    current_version: str,
    fetch: Fetch = http_fetch,
) -> str | None:
    """Downloads, verifies and installs the latest release on ``channel``.

    Returns the installed version, or ``None`` when ``current_version`` is
    already as new.
    """
    tag, assets = latest_release(channel, fetch)
    if version_key(tag) <= version_key(current_version):
        return None
    sums = fetch(assets[SUMS], MAX_SMALL_BYTES)
    signature = fetch(assets[SIGNATURE], MAX_SMALL_BYTES)
    expected = signed_hash(sums, signature)
    archive = fetch(assets[ASSET], MAX_ASSET_BYTES)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise UpdateError("update_verification_failed")

    tools_dir.mkdir(parents=True, exist_ok=True)
    staging = tools_dir / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        (staging / ASSET).write_bytes(archive)
        (staging / SUMS).write_bytes(sums)
        (staging / SIGNATURE).write_bytes(signature)
        with zipfile.ZipFile(staging / ASSET) as bundle:
            version_source = bundle.read("yt_dlp/version.py").decode("utf-8", "replace")
        if f"__version__ = '{tag}'" not in version_source:
            raise UpdateError("update_verification_failed")
        (staging / "version.json").write_text(
            json.dumps({"version": tag, "channel": channel}), encoding="utf-8"
        )
        current = _current_dir(tools_dir)
        previous = tools_dir / "previous"
        shutil.rmtree(previous, ignore_errors=True)
        if current.exists():
            current.rename(previous)
        staging.rename(current)
        shutil.rmtree(previous, ignore_errors=True)
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("update_failed") from error
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return tag
