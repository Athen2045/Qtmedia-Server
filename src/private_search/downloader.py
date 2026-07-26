import importlib.util
import os
import re
import shutil
from urllib.parse import urlparse

from .config import DOWNLOAD_ROOT, ensure_runtime_directories
from .pmvhaven import fetch_metadata, is_pmvhaven_url


# Optional proxy configuration. Leave empty to connect directly.
PROXIES = {}

ensure_runtime_directories()
OUTPUT_FOLDER = str(DOWNLOAD_ROOT)


def is_direct_video_url(video_url):
    """Reject site homepages and known non-video URLs before yt-dlp runs."""
    parsed = urlparse(video_url)
    host = parsed.netloc.casefold().split(":", 1)[0]
    path = parsed.path.rstrip("/")

    if parsed.scheme not in {"http", "https"} or not host or not path:
        return False
    if "..." in video_url:
        return False

    if host.endswith("xvideos.com"):
        return bool(re.search(r"/video(?:\.|\d)[^/]*", path))
    if host.endswith("xhamster.com"):
        return path.startswith("/videos/") and len(path) > len("/videos/")
    if host.endswith("spankbang.com"):
        return "/video/" in f"{path}/" and len(path.rsplit("/video/", 1)[-1]) > 0
    return True


def build_ydl_options():
    options = {
        "format": "bestvideo+bestaudio/best",
        "noplaylist": True,
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(OUTPUT_FOLDER, "%(title)s [%(id)s].%(ext)s"),
    }
    if PROXIES.get("https"):
        options["proxy"] = PROXIES["https"]
    # Cloudflare-protected sites may require browser impersonation. This
    # option is only enabled when yt-dlp's optional curl-cffi dependency is
    # installed.
    if importlib.util.find_spec("curl_cffi"):
        options["extractor_args"] = {
            "generic": {"impersonate": [""]},
        }
    return options


def download_video(video_url):
    if not is_direct_video_url(video_url):
        print(f"Skipping non-video URL: {video_url}")
        return
    download_url = video_url
    output_title = None
    output_id = None
    if is_pmvhaven_url(video_url):
        try:
            metadata = fetch_metadata(video_url)
            print(f"PMVHaven title: {metadata.title}")
            if not metadata.media_url:
                print("PMVHaven API did not provide a downloadable media URL.")
                return
            download_url = metadata.media_url
            print(f"PMVHaven media source: {download_url}")
            output_title = re.sub(r"[\\/:*?\"<>|]+", "_", metadata.title).strip() or "video"
            output_id = metadata.video_id
        except (requests.RequestException, TypeError, ValueError) as error:
            print(f"PMVHaven API validation failed: {error}")
            return

    if shutil.which("ffmpeg") is None:
        print("ffmpeg is required to merge and repair MP4 streams.")
        print("Install it with: brew install ffmpeg")
        return

    print(f"Downloading: {video_url}")
    import yt_dlp

    try:
        options = build_ydl_options()
        if output_title and output_id:
            options["outtmpl"] = os.path.join(
                OUTPUT_FOLDER, f"{output_title} [{output_id}].%(ext)s"
            )
        with yt_dlp.YoutubeDL(options) as ydl:
            error_code = ydl.download([download_url])
        if error_code:
            print(f"Download failed for {video_url} (exit code {error_code})")
        else:
            print(f"Download complete: {OUTPUT_FOLDER}")
    except yt_dlp.utils.DownloadError as error:
        print(f"Error downloading {video_url}: {error}")


def main():
    print("Paste a direct video URL to download it as MP4.")
    print("Type 'q' or 'quit' to exit.")

    while True:
        try:
            video_url = input("Enter Link: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return

        if video_url.casefold() in {"q", "quit", "exit"}:
            print("Exiting.")
            return
        if not video_url:
            print("Please enter a URL.")
            continue
        if not is_direct_video_url(video_url):
            print("Please enter a direct video URL, not a homepage or placeholder URL.")
            continue
        download_video(video_url)


if __name__ == "__main__":
    main()
