"""Privacy-aware, metadata-only source inspection for bot requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import requests

from ...download.transfer import common_ydl_options
from ...net import http_client
from ...sources.pmvhaven import (
    MEDIA_DOMAINS as PMVHAVEN_MEDIA_DOMAINS,
)
from ...sources.pmvhaven import (
    fetch_metadata,
    is_pmvhaven_url,
)
from ..sources.adapters import adapter_for_url, inspection_candidates
from .quality import positive_int
from .source_policy import SourcePolicyError, validate_source_url
from .yt_options import (
    browser_cookie_options,
    javascript_runtime_options,
    privacy_safe_logger_options,
)

DIRECT_MEDIA_PROBE_TIMEOUT_SECONDS = 20


class InspectionError(RuntimeError):
    """A source could not be inspected within bot policy limits."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BestAvailableCandidate:
    """An exact-size direct media candidate retained only for an active job."""

    url: str
    size_bytes: int
    validation_domains: frozenset[str]


@dataclass(frozen=True, slots=True)
class MediaInspection:
    """The minimal in-memory metadata needed to build quality options."""

    url: str
    title: str
    duration_seconds: int | None
    formats: tuple[Mapping[str, object], ...]
    download_url: str | None = None
    best_available: BestAvailableCandidate | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedInspectionSource:
    """Provider resolution details kept behind the inspection seam."""

    url: str
    title: str | None = None
    best_available: BestAvailableCandidate | None = None


def _ydl_options(url: str, *, force_generic: bool = False) -> dict[str, object]:
    options = {
        **common_ydl_options(),
        **javascript_runtime_options(),
        **browser_cookie_options(url),
        **privacy_safe_logger_options(),
        "skip_download": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    adapter = adapter_for_url(url)
    profile = adapter.impersonate if adapter is not None else None
    target = http_client.ytdlp_impersonate_target(profile) if profile else None
    if target:
        from yt_dlp.networking.impersonate import (  # pylint: disable=import-outside-toplevel
            ImpersonateTarget,
        )

        options["impersonate"] = ImpersonateTarget.from_str(target)
    if force_generic:
        options["force_generic_extractor"] = True
    return options


def _duration_seconds(info: Mapping[str, object]) -> int | None:
    raw_duration = info.get("duration")
    if raw_duration is None:
        return None
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise InspectionError(
            "invalid_metadata", "The source returned invalid metadata."
        ) from exc
    if duration < 0:
        raise InspectionError(
            "invalid_metadata", "The source returned invalid metadata."
        )
    return int(duration)


def probe_exact_video_size(url: str) -> int | None:
    """Return a direct video's exact length without following redirects."""

    try:
        response = requests.head(
            url,
            headers={"User-Agent": "qtmedia-bot/0.1"},
            timeout=DIRECT_MEDIA_PROBE_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException:
        return None
    content_type = str(response.headers.get("Content-Type") or "")
    if response.status_code != 200 or not content_type.casefold().startswith("video/"):
        return None
    return positive_int(response.headers.get("Content-Length"))


def _metadata_best_candidate(
    info: Mapping[str, object], settings
) -> BestAvailableCandidate | None:
    """Accept only an exact-size direct URL covered by normal source policy."""

    candidate_url = info.get("url")
    if not isinstance(candidate_url, str):
        return None
    try:
        validate_source_url(candidate_url, settings.allowed_domains)
    except SourcePolicyError:
        return None
    size_bytes = probe_exact_video_size(candidate_url)
    if size_bytes is None:
        return None
    return BestAvailableCandidate(
        candidate_url,
        size_bytes,
        settings.allowed_domains,
    )


def _resolve_inspection_source(url: str) -> _ResolvedInspectionSource:
    """Resolve provider-owned media while keeping the submitted URL in memory."""

    if not is_pmvhaven_url(url):
        return _ResolvedInspectionSource(url)
    try:
        metadata = fetch_metadata(url)
    except (requests.RequestException, TypeError, ValueError) as exc:
        raise InspectionError(
            "source_unavailable", "The source could not be inspected."
        ) from exc
    media_url = metadata.media_url
    if not media_url:
        raise InspectionError(
            "source_unavailable", "The source could not be inspected."
        )
    try:
        validate_source_url(media_url, PMVHAVEN_MEDIA_DOMAINS)
    except SourcePolicyError as exc:
        raise InspectionError(
            "provider_media_rejected", "The source could not be inspected."
        ) from exc
    best_available = None
    if metadata.video_url:
        try:
            validate_source_url(metadata.video_url, PMVHAVEN_MEDIA_DOMAINS)
        except SourcePolicyError:
            pass
        else:
            size_bytes = probe_exact_video_size(metadata.video_url)
            if size_bytes is not None:
                best_available = BestAvailableCandidate(
                    metadata.video_url,
                    size_bytes,
                    PMVHAVEN_MEDIA_DOMAINS,
                )
    return _ResolvedInspectionSource(media_url, metadata.title, best_available)


def _extract_with_fallbacks(
    url: str, resolved_url: str
) -> tuple[str, Mapping[str, object]]:
    """Try provider page variants before reporting an inspection failure."""

    import yt_dlp  # pylint: disable=import-outside-toplevel

    adapter = adapter_for_url(url)
    last_info: tuple[str, Mapping[str, object]] | None = None
    last_error: Exception | None = None
    for candidate_url, force_generic in inspection_candidates(url, resolved_url):
        try:
            with yt_dlp.YoutubeDL(
                _ydl_options(candidate_url, force_generic=force_generic)
            ) as ydl:
                info = ydl.extract_info(candidate_url, download=False)
        except (
            yt_dlp.utils.DownloadError,
            AttributeError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            last_error = exc
            continue
        if not isinstance(info, Mapping):
            last_error = TypeError("extractor returned non-mapping metadata")
            continue
        if info.get("entries"):
            # A playlist result is not a useful fallback for a single video
            # page; keep trying a provider's alternate page form.
            last_error = InspectionError(
                "playlist_not_supported", "Playlists are not supported."
            )
            continue
        if adapter is None:
            return candidate_url, info
        last_info = (candidate_url, info)
        raw_formats = info.get("formats")
        if isinstance(raw_formats, list) and raw_formats:
            return candidate_url, info
        if info.get("url"):
            return candidate_url, info
        last_error = InspectionError(
            "source_unavailable", "The source returned no media formats."
        )

    if isinstance(last_error, InspectionError) and last_error.code == (
        "playlist_not_supported"
    ):
        raise last_error
    if last_info is not None:
        return last_info
    raise InspectionError(
        "source_unavailable", "The source could not be inspected."
    ) from last_error


def inspect_source(url: str, settings) -> MediaInspection:
    """Validate and inspect one source without downloading or persisting it."""

    validate_source_url(url, settings.allowed_domains)
    resolved = _resolve_inspection_source(url)
    inspection_url = resolved.url
    extracted_url, info = _extract_with_fallbacks(url, inspection_url)

    duration = _duration_seconds(info)
    if duration is not None and duration > settings.max_duration_seconds:
        raise InspectionError(
            "duration_limit", "This media exceeds the duration limit."
        )

    raw_formats = info.get("formats")
    formats = (
        tuple(dict(item) for item in raw_formats if isinstance(item, Mapping))
        if isinstance(raw_formats, list)
        else ()
    )
    title = str(
        resolved.title or info.get("title") or info.get("id") or "Untitled media"
    )
    return MediaInspection(
        url=url,
        title=title,
        duration_seconds=duration,
        formats=formats,
        download_url=extracted_url if extracted_url != url else None,
        best_available=(
            resolved.best_available or _metadata_best_candidate(info, settings)
        ),
    )
