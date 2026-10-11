"""Non-interactive yt-dlp transfer primitives for the desktop sidecar."""

from __future__ import annotations

import contextlib
import ipaddress
import os
import re
import shutil
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..download.transfer import common_ydl_options
from ..net import http_client
from .adapters import impersonate_for_url
from .browser_cookies import site_ydl_options
from .models import (
    DownloadProgress,
    DownloadResult,
    InspectedMedia,
    MediaLibrary,
)
from .network import new_session as network_session
from .network import proxy_options
from .runtime import javascript_runtime_options
from .song_tags import write_song_tags
from .ytdlp_errors import is_source_blocked, is_source_changed

ProgressCallback = Callable[[DownloadProgress], None]
INVALID_FILENAME = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
MAX_ARTWORK_BYTES = 8 * 1024 * 1024
CLEANUP_ATTEMPTS = 15
CLEANUP_RETRY_SECONDS = 0.2
ARTWORK_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class DesktopDownloadCancelled(RuntimeError):
    pass


def safe_stem(title: str, media_id: str) -> str:
    cleaned = INVALID_FILENAME.sub("_", title).strip(" ._") or "media"
    return f"{cleaned[:120]} [{media_id}]"


# Postprocessors whose work is worth naming. MoveFiles (a rename) and the
# thumbnail conversion (runs before the download) are instant and silent.
POSTPROCESSOR_STAGES = {"Merger": "merging", "ExtractAudio": "converting"}
SILENT_POSTPROCESSORS = frozenset({"MoveFiles", "ThumbnailsConvertor"})


def stream_count(selector: str, kind: str) -> int:
    """Streams yt-dlp downloads for a selector (``video+audio`` merges two)."""
    if kind != "video":
        return 1
    return selector.split("/", 1)[0].count("+") + 1


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _stream_name(info: object) -> str | None:
    if not isinstance(info, dict):
        return None
    if info.get("vcodec") == "none":
        return "audio"
    if info.get("acodec") == "none":
        return "video"
    return None


def _progress_hook(
    progress: ProgressCallback,
    cancel: threading.Event,
    *,
    parts: int = 1,
) -> Callable[[dict[str, object]], None]:
    # yt-dlp hides the other requested formats from each stream's hook, so
    # streams are numbered in the order their files appear.
    files: list[str] = []

    def hook(status: dict[str, object]) -> None:
        if cancel.is_set():
            raise DesktopDownloadCancelled("cancelled")
        if status.get("status") != "downloading":
            return
        filename = str(status.get("filename") or "")
        if filename not in files:
            files.append(filename)
        part = min(files.index(filename) + 1, max(parts, 1))
        downloaded = int(status.get("downloaded_bytes") or 0)
        exact = _number(status.get("total_bytes"))
        estimate = _number(status.get("total_bytes_estimate"))
        fragment_index = _number(status.get("fragment_index"))
        fragment_count = _number(status.get("fragment_count"))
        if exact:
            percent = downloaded * 100 / exact
        elif fragment_count and fragment_index is not None:
            # HLS size estimates jump around; fragments done is the real measure.
            percent = fragment_index * 100 / fragment_count
        elif estimate:
            percent = downloaded * 100 / estimate
        else:
            percent = None
        total = exact or estimate
        progress(
            DownloadProgress(
                downloaded,
                int(total) if total else None,
                min(100.0, percent) if percent is not None else None,
                stream=_stream_name(status.get("info_dict")) if parts > 1 else None,
                part=part,
                parts=max(parts, 1),
            )
        )

    return hook


def _postprocessor_hook(
    progress: ProgressCallback,
    cancel: threading.Event,
) -> Callable[[dict[str, object]], None]:
    def hook(status: dict[str, object]) -> None:
        if cancel.is_set():
            raise DesktopDownloadCancelled("cancelled")
        name = str(status.get("postprocessor") or "")
        if status.get("status") != "started" or name in SILENT_POSTPROCESSORS:
            return
        progress(DownloadProgress.stage_only(POSTPROCESSOR_STAGES.get(name, "processing")))

    return hook


def build_download_options(
    media: InspectedMedia,
    format_key: str,
    library: MediaLibrary,
    progress: ProgressCallback,
    cancel: threading.Event,
) -> dict[str, object]:
    selection = media.selection_for(format_key)
    kind = selection.kind
    stem = safe_stem(media.title, media.media_id)
    options: dict[str, object] = {
        **common_ydl_options(),
        **javascript_runtime_options(),
        **proxy_options(),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # quiet alone still prints the console progress bar to stdout.
        "noprogress": True,
        "paths": {"home": str(library.temp), "temp": str(library.temp)},
        "outtmpl": str(library.temp / f"{stem}.%(ext)s"),
        "progress_hooks": [
            _progress_hook(progress, cancel, parts=stream_count(selection.selector, kind))
        ],
        "postprocessor_hooks": [_postprocessor_hook(progress, cancel)],
        "extractor_retries": http_client.RETRY_ATTEMPTS,
    }
    bundled_ffmpeg = os.getenv("QTMEDIA_FFMPEG")
    if bundled_ffmpeg and Path(bundled_ffmpeg).is_file():
        options["ffmpeg_location"] = bundled_ffmpeg
    if kind == "video":
        options.update(
            {
                "format": selection.selector,
                "merge_output_format": "mp4",
            }
        )
    elif selection.extension == "flac":
        # Cover art goes into the FLAC PICTURE block (yt-dlp uses mutagen).
        options.update(
            {
                "format": selection.selector,
                "writethumbnail": True,
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "flac"},
                    {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                    {"key": "EmbedThumbnail"},
                ],
            }
        )
    else:
        options.update(
            {
                "format": selection.selector,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        # LAME V0 (VBR, ~245 kbps): the least added loss when
                        # re-encoding a lossy stream to MP3.
                        "preferredquality": "0",
                    }
                ],
            }
        )
    # Impersonation, and the user's Firefox cookies where opted in.
    options.update(site_ydl_options(media.source_url))
    return options


def _collision_safe(destination: Path) -> Path:
    if not destination.exists():
        return destination
    for index in range(2, 10_000):
        candidate = destination.with_name(f"{destination.stem} ({index}){destination.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("filename_exhausted")


def _validate_public_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("unsafe_artwork")
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as error:
        raise ValueError("unsafe_artwork") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("unsafe_artwork")


def _download_artwork(media: InspectedMedia, library: MediaLibrary, stem: str) -> str | None:
    if not media.thumbnail_url:
        return None
    session = network_session(impersonate_for_url(media.source_url))
    current = media.thumbnail_url
    part = library.temp / f"{stem}.artwork.part"
    try:
        for _redirect in range(4):
            _validate_public_http_url(current)
            response = http_client.get(
                session,
                current,
                allow_redirects=False,
                stream=True,
                timeout=(5, 15),
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                response.close()
                if not location:
                    raise ValueError("artwork_failed")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
            extension = ARTWORK_TYPES.get(content_type)
            if extension is None:
                response.close()
                raise ValueError("artwork_failed")
            written = 0
            try:
                with part.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_ARTWORK_BYTES:
                            raise ValueError("artwork_failed")
                        output.write(chunk)
            finally:
                response.close()
            if written == 0:
                raise ValueError("artwork_failed")
            destination = _collision_safe(library.artwork / f"{stem}{extension}")
            os.replace(part, destination)
            return destination.relative_to(library.root).as_posix()
        raise ValueError("artwork_failed")
    finally:
        part.unlink(missing_ok=True)
        close = getattr(session, "close", None)
        if close:
            close()


def _cleanup_job_files(library: MediaLibrary, stem: str) -> None:
    """Remove this job's temp files without ever masking the job's outcome.

    After a cancel, yt-dlp fragment threads may briefly keep files open, which
    Windows refuses to delete. Retry for a short while; anything still locked is
    removed by the startup sweep in ``MediaLibrary.create``.
    """
    for attempt in range(CLEANUP_ATTEMPTS):
        locked = False
        for candidate in library.temp.iterdir():
            if not candidate.name.startswith(stem):
                continue
            try:
                if candidate.is_symlink() or candidate.is_file():
                    candidate.unlink(missing_ok=True)
                elif candidate.is_dir():
                    shutil.rmtree(candidate)
            except OSError:
                locked = True
        if not locked:
            return
        if attempt + 1 < CLEANUP_ATTEMPTS:
            time.sleep(CLEANUP_RETRY_SECONDS)


def download_media(
    media: InspectedMedia,
    format_key: str,
    library: MediaLibrary,
    progress: ProgressCallback,
    cancel: threading.Event,
) -> DownloadResult:
    import yt_dlp

    stem = safe_stem(media.title, media.media_id)
    try:
        selection = media.selection_for(format_key)
        kind = selection.kind
        options = build_download_options(media, format_key, library, progress, cancel)
        source = media.download_url or media.source_url
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                error_code = ydl.download([source])
        except DesktopDownloadCancelled:
            raise
        except Exception as error:
            # yt-dlp wraps the progress hook's cancellation in DownloadError.
            if cancel.is_set():
                raise DesktopDownloadCancelled("cancelled") from None
            if is_source_blocked(error):
                raise RuntimeError("source_blocked") from error
            if is_source_changed(error):
                raise RuntimeError("source_changed") from error
            raise
        if cancel.is_set():
            raise DesktopDownloadCancelled("cancelled")
        if error_code:
            raise RuntimeError("download_failed")
        progress(DownloadProgress.stage_only("saving"))
        extension = selection.extension or ("mp3" if kind == "audio" else "mp4")
        candidates = sorted(
            candidate
            for candidate in library.temp.iterdir()
            if candidate.name.startswith(stem) and candidate.suffix.casefold() == f".{extension}"
        )
        if not candidates or candidates[0].is_symlink() or candidates[0].stat().st_size == 0:
            raise RuntimeError("output_missing")
        target_root = library.audio if kind == "audio" else library.video
        destination = _collision_safe(target_root / f"{stem}.{extension}")
        os.replace(candidates[0], destination)
        if kind == "audio" and not media.tags.is_empty():
            # Only real music metadata is written (never a guessed artist).
            # Tags are best effort, like artwork: a failure keeps the file.
            with contextlib.suppress(Exception):
                write_song_tags(destination, media.tags, media.title)
        try:
            artwork_path = _download_artwork(media, library, destination.stem)
        except Exception:  # noqa: BLE001 - artwork is explicitly best effort
            artwork_path = None
        saved = destination.stat()
        return DownloadResult(
            relative_path=destination.relative_to(library.root).as_posix(),
            title=media.title,
            media_type=kind,
            extension=extension,
            artwork_path=artwork_path,
            size_bytes=saved.st_size,
            modified_at=saved.st_mtime,
        )
    finally:
        _cleanup_job_files(library, stem)
