"""Kitty terminal thumbnail previews for inspected video results."""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from ..config import CACHE_ROOT, ensure_runtime_directories
from ..net import http_client

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - dependency is declared in pyproject.toml
    Image = None
    ImageOps = None

THUMBNAIL_CACHE = CACHE_ROOT / "thumbnails"
THUMBNAIL_TIMEOUT = 15
MAX_THUMBNAIL_BYTES = 4 * 1024 * 1024
PREVIEW_WIDTH_CELLS = 36
PREVIEW_HEIGHT_CELLS = 14
PREVIEW_WIDTH_PIXELS = 720
PREVIEW_HEIGHT_PIXELS = 360


class ThumbnailError(RuntimeError):
    """An expected thumbnail download or conversion failure."""


THUMBNAIL_EXCEPTIONS = (OSError, ThumbnailError, *http_client.HTTP_EXCEPTIONS)


def is_kitty_terminal() -> bool:
    """Return whether the current process appears to run inside Kitty."""
    term = os.getenv("TERM", "").casefold()
    return bool(os.getenv("KITTY_WINDOW_ID")) or term.startswith("xterm-kitty")


def render_thumbnail(url: str | None) -> bool:
    """Download, cache, and render one thumbnail using Kitty graphics."""
    if not url or not is_kitty_terminal():
        return False
    try:
        thumbnail = _prepare_thumbnail(url)
        _write_kitty_png(thumbnail)
    except THUMBNAIL_EXCEPTIONS:
        return False
    return True


def render_local_image(path: Path) -> bool:
    """Render one local image through Kitty graphics when available."""
    if not is_kitty_terminal() or Image is None or ImageOps is None:
        return False

    preview_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            preview_path = Path(temp_file.name)
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((PREVIEW_WIDTH_PIXELS, PREVIEW_HEIGHT_PIXELS))
            image.convert("RGBA").save(preview_path, format="PNG", optimize=True)
        _write_kitty_png(preview_path)
    except (OSError, ValueError):
        return False
    finally:
        if preview_path is not None:
            preview_path.unlink(missing_ok=True)
    return True


def _prepare_thumbnail(url: str) -> Path:
    ensure_runtime_directories()
    THUMBNAIL_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    source = THUMBNAIL_CACHE / f"{key}.source"
    preview = THUMBNAIL_CACHE / f"{key}.png"
    if preview.is_file() and preview.stat().st_size:
        return preview
    if not source.is_file() or not source.stat().st_size:
        _download_source(url, source)
    if Image is None or ImageOps is None:
        raise ThumbnailError("Pillow is required to prepare Kitty previews.")
    try:
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((PREVIEW_WIDTH_PIXELS, PREVIEW_HEIGHT_PIXELS))
            image.convert("RGBA").save(preview, format="PNG", optimize=True)
    except (OSError, ValueError) as error:
        preview.unlink(missing_ok=True)
        raise ThumbnailError(f"Could not convert thumbnail: {error}") from error
    return preview


def _download_source(url: str, destination: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ThumbnailError("Thumbnail URL must use HTTP or HTTPS.")
    temporary = destination.with_suffix(".part")
    try:
        with http_client.new_session() as session:
            response = http_client.get(
                session,
                url,
                headers=http_client.request_headers(),
                timeout=THUMBNAIL_TIMEOUT,
                stream=True,
            )
            try:
                response.raise_for_status()
                total = 0
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_THUMBNAIL_BYTES:
                            raise ThumbnailError("Thumbnail exceeds the 4 MiB preview limit.")
                        output.write(chunk)
            finally:
                response.close()
        os.replace(temporary, destination)
    except THUMBNAIL_EXCEPTIONS:
        temporary.unlink(missing_ok=True)
        raise


def _write_kitty_png(path: Path) -> None:
    encoded = base64.b64encode(path.read_bytes())
    stream = sys.stdout.buffer
    chunk_size = 4096
    for offset in range(0, len(encoded), chunk_size):
        chunk = encoded[offset : offset + chunk_size]
        first = offset == 0
        last = offset + chunk_size >= len(encoded)
        controls = "a=T,f=100,q=2"
        if first:
            controls += f",c={PREVIEW_WIDTH_CELLS},r={PREVIEW_HEIGHT_CELLS}"
        controls += f",m={0 if last else 1}"
        stream.write(f"\x1b_G{controls};".encode("ascii"))
        stream.write(chunk)
        stream.write(b"\x1b\\")
    stream.flush()
    sys.stdout.write("\n")
