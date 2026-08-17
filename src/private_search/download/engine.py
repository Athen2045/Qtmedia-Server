import os
import re
import shutil
from urllib.parse import urlparse

import requests

from ..config import DOWNLOAD_ROOT, ensure_runtime_directories
from ..net import http_client
from ..search.engine import adapter_for_host, impersonate_for_url, is_video_candidate
from ..sources.pmvhaven import fetch_metadata, is_pmvhaven_url
from .control import DownloadCancellation, DownloadCancelled, DownloadProgressCallback
from .transfer import download_ydl_options

# Optional proxy configuration, set via the PRIVATE_SEARCH_PROXY env var.
# Leave unset to connect directly.
PROXIES = {"https": proxy} if (proxy := os.getenv("PRIVATE_SEARCH_PROXY", "").strip()) else {}

ensure_runtime_directories()
OUTPUT_FOLDER = str(DOWNLOAD_ROOT)


def is_direct_video_url(video_url: str) -> bool:
    """Reject site homepages and known non-video URLs before yt-dlp runs.

    Delegates to the same SiteAdapter rules the search pipeline uses (see
    ``search.engine``), so a site rule only needs to change in one place.
    """
    parsed = urlparse(video_url)
    host = parsed.netloc.casefold().split(":", 1)[0]
    path = parsed.path.rstrip("/")

    if parsed.scheme not in {"http", "https"} or not host or not path:
        return False
    if "..." in video_url:
        return False

    adapter = adapter_for_host(host)
    if adapter is not None:
        return is_video_candidate(adapter, path)
    return True


def build_ydl_options(video_url: str | None = None) -> dict[str, object]:
    options = {
        **download_ydl_options(),
        "format": "bestvideo+bestaudio/best",
        "noplaylist": True,
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(OUTPUT_FOLDER, "%(title)s [%(id)s].%(ext)s"),
    }
    if PROXIES.get("https"):
        options["proxy"] = PROXIES["https"]
    # Cloudflare-protected sites may require browser impersonation, on the
    # video page as much as on the search page. The top-level option covers
    # every request yt-dlp makes; the ``extractor_args`` form this replaced
    # only reached the generic extractor, so site-specific extractors still
    # presented yt-dlp's own fingerprint and got reset.
    target = http_client.ytdlp_impersonate_target(
        impersonate_for_url(video_url) if video_url else None
    )
    if target:
        from yt_dlp.networking.impersonate import (  # pylint: disable=import-outside-toplevel
            ImpersonateTarget,
        )

        options["impersonate"] = ImpersonateTarget.from_str(target)
    return options


def download_video(
    video_url: str,
    progress: DownloadProgressCallback | None = None,
) -> bool:
    if not is_direct_video_url(video_url):
        print(f"Skipping non-video URL: {video_url}")
        return False
    download_url = video_url
    output_title = None
    output_id = None
    if is_pmvhaven_url(video_url):
        try:
            metadata = fetch_metadata(video_url)
            print(f"PMVHaven title: {metadata.title}")
            if not metadata.media_url:
                print("PMVHaven API did not provide a downloadable media URL.")
                return False
            download_url = metadata.media_url
            print(f"PMVHaven media source: {download_url}")
            output_title = re.sub(r"[\\/:*?\"<>|]+", "_", metadata.title).strip() or "video"
            output_id = metadata.video_id
        except (requests.RequestException, TypeError, ValueError) as error:
            print(f"PMVHaven API validation failed: {error}")
            return False

    if shutil.which("ffmpeg") is None:
        print("ffmpeg is required to merge and repair MP4 streams.")
        print("Install FFmpeg and ensure ffmpeg.exe is on PATH.")
        return False

    print(f"Downloading: {video_url}")
    import yt_dlp

    try:
        options = build_ydl_options(video_url)
        if output_title and output_id:
            options["outtmpl"] = os.path.join(
                OUTPUT_FOLDER, f"{output_title} [{output_id}].%(ext)s"
            )
        cancellation = DownloadCancellation()
        options["progress_hooks"] = [cancellation.progress_hook]
        if progress is not None:
            options["progress_hooks"].append(progress)
            options["quiet"] = True
            options["no_warnings"] = True
        cancellation.start()
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                error_code = ydl.download([download_url])
        finally:
            cancellation.stop()
        if error_code:
            print(f"Download failed for {video_url} (exit code {error_code})")
            return False
        else:
            print(f"Download complete: {OUTPUT_FOLDER}")
            return True
    except DownloadCancelled:
        print("Download cancelled by user.")
        return False
    except yt_dlp.utils.DownloadError as error:
        print(f"Error downloading {video_url}: {error}")
        return False
