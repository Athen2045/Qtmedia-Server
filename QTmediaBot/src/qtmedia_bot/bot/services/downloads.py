"""Bounded, privacy-aware media downloads for Telegram jobs."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ...download.transfer import common_ydl_options
from ...net import http_client
from ...sources.pmvhaven import (
    MEDIA_DOMAINS as PMVHAVEN_MEDIA_DOMAINS,
)
from ...sources.pmvhaven import (
    is_pmvhaven_url,
)
from ..sources.adapters import adapter_for_url
from ..storage import JobMetadataStore
from .delivery import (
    VIDEO_SUFFIXES,
    DeliverableMedia,
    DeliveryError,
    DeliveryTransport,
    TelegramDeliveryTransport,
)
from .inspection import probe_exact_video_size
from .metrics import JobPhaseRecorder
from .progress import DownloadProgress, TelegramProgressReporter
from .quality import BEST_AVAILABLE_KEY
from .source_policy import validate_source_url
from .yt_options import (
    browser_cookie_options,
    javascript_runtime_options,
    privacy_safe_logger_options,
)

logger = logging.getLogger(__name__)

AUDIO_SUFFIXES = frozenset({".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"})
OUTPUT_SUFFIXES = VIDEO_SUFFIXES | AUDIO_SUFFIXES
UNCONFIRMED_UPLOAD_MARKER = ".upload-unconfirmed"


def _audio_output_suffix(audio_format: str | None) -> str:
    """Map an audio codec choice to its post-processed file suffix."""

    if audio_format == "alac":
        return ".m4a"
    return f".{audio_format or 'mp3'}"


class DownloadError(RuntimeError):
    """A controlled download or output-validation failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class DownloadCancelled(DownloadError):
    """A download stopped because its cancellation event was set."""

    def __init__(self):
        super().__init__("cancelled")


DownloadedMedia = DeliverableMedia


def cleanup_job_directory(job_root: Path, job_id: str) -> None:
    """Remove one job directory without following an unsafe symlink."""

    root = job_root.resolve()
    target = job_root / job_id
    if target.is_symlink():
        target.unlink()
        return
    resolved_target = target.resolve()
    if resolved_target == root or root not in resolved_target.parents:
        raise ValueError("job directory is outside the configured root")
    if target.exists():
        shutil.rmtree(target)


def cleanup_orphaned_job_directories(
    job_root: Path,
    *,
    max_age_seconds: int,
    unconfirmed_max_age_seconds: int | None = None,
    time_fn: Callable[[], float] = time.time,
) -> int:
    """Remove stale direct-child job directories left by an interrupted run."""

    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    job_root.mkdir(parents=True, exist_ok=True)
    now = time_fn()
    removed = 0
    for candidate in job_root.iterdir():
        if not candidate.is_symlink() and not candidate.is_dir():
            continue
        candidate_max_age = max_age_seconds
        marker = candidate / UNCONFIRMED_UPLOAD_MARKER
        if marker.is_file() and unconfirmed_max_age_seconds is not None:
            candidate_max_age = unconfirmed_max_age_seconds
        if candidate.is_symlink() or candidate.stat().st_mtime <= (
            now - candidate_max_age
        ):
            cleanup_job_directory(job_root, candidate.name)
            removed += 1
    return removed


def _mark_unconfirmed_upload(job_root: Path, job_id: str) -> None:
    """Mark an opaque job directory for delayed, restart-safe cleanup."""

    root = job_root.resolve()
    job_dir = job_root / job_id
    if job_dir.is_symlink():
        raise ValueError("job directory cannot be a symlink")
    resolved_job_dir = job_dir.resolve()
    if resolved_job_dir == root or root not in resolved_job_dir.parents:
        raise ValueError("job directory is outside the configured root")
    if job_dir.is_dir():
        (job_dir / UNCONFIRMED_UPLOAD_MARKER).touch(exist_ok=True)


def retained_upload_cleanup_delays(
    job_root: Path,
    *,
    retention_seconds: float,
    time_fn: Callable[[], float] = time.time,
) -> tuple[tuple[str, float], ...]:
    """Return opaque retained job IDs and their remaining cleanup delays."""

    if retention_seconds <= 0:
        raise ValueError("retention_seconds must be positive")
    if not job_root.exists():
        return ()
    now = time_fn()
    retained: list[tuple[str, float]] = []
    for candidate in job_root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        marker = candidate / UNCONFIRMED_UPLOAD_MARKER
        if marker.is_file() and not marker.is_symlink():
            age = max(0.0, now - marker.stat().st_mtime)
            retained.append((candidate.name, max(0.0, retention_seconds - age)))
    return tuple(retained)


def _disk_has_reserve(job_root: Path, reserve_bytes: int, output_cap: int) -> bool:
    usage = shutil.disk_usage(job_root)
    return usage.free >= reserve_bytes + output_cap


def _non_negative_int(value: object) -> int | None:
    """Normalize yt-dlp numeric fields without forwarding arbitrary hook data."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    normalized = int(value)
    return normalized if normalized >= 0 else None


def _progress_hook(
    cancel_event: threading.Event,
    progress_callback: Callable[[DownloadProgress], None] | None = None,
):
    def check_cancelled(status: dict[str, object]) -> None:
        if cancel_event.is_set():
            raise DownloadCancelled()
        if progress_callback is None or status.get("status") != "downloading":
            return
        downloaded_bytes = _non_negative_int(status.get("downloaded_bytes"))
        if downloaded_bytes is None:
            return
        progress_callback(
            DownloadProgress(
                downloaded_bytes=downloaded_bytes,
                total_bytes=_non_negative_int(status.get("total_bytes")),
                estimated_total_bytes=_non_negative_int(
                    status.get("total_bytes_estimate")
                ),
                speed_bytes_per_second=_non_negative_int(status.get("speed")),
            )
        )

    return check_cancelled


def _postprocessor_hook(
    cancel_event: threading.Event,
    preparing_callback: Callable[[], None] | None = None,
):
    def check_cancelled(status: dict[str, object]) -> None:
        if cancel_event.is_set():
            raise DownloadCancelled()
        if preparing_callback is not None and status.get("status") in {
            "started",
            "processing",
        }:
            preparing_callback()

    return check_cancelled


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _ydl_options(
    record_url: str,
    option,
    job_dir: Path,
    settings,
    cancel_event: threading.Event,
    progress_callback: Callable[[DownloadProgress], None] | None = None,
    preparing_callback: Callable[[], None] | None = None,
) -> dict[str, object]:
    options: dict[str, object] = {
        **common_ydl_options(),
        **javascript_runtime_options(),
        **browser_cookie_options(record_url),
        **privacy_safe_logger_options(),
        "format": option.format_selector,
        "outtmpl": str(job_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": settings.max_upload_bytes,
        "progress_hooks": [_progress_hook(cancel_event, progress_callback)],
        "postprocessor_hooks": [_postprocessor_hook(cancel_event, preparing_callback)],
    }
    if option.media_type == "audio":
        audio_format = option.audio_format or "mp3"
        if audio_format == "mp3":
            postprocessor = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        elif audio_format == "m4a":
            postprocessor = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "256",
            }
        else:
            raise DownloadError("output_format")
        options["postprocessors"] = [postprocessor]
    elif option.media_type == "document":
        if option.audio_format not in {"flac", "alac"}:
            raise DownloadError("output_format")
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": option.audio_format,
            }
        ]
    else:
        options["merge_output_format"] = "mp4"

    adapter = adapter_for_url(record_url)
    profile = adapter.impersonate if adapter is not None else None
    target = http_client.ytdlp_impersonate_target(profile) if profile else None
    if target:
        from yt_dlp.networking.impersonate import (  # pylint: disable=import-outside-toplevel
            ImpersonateTarget,
        )

        options["impersonate"] = ImpersonateTarget.from_str(target)
    return options


def _validated_output(
    job_dir: Path,
    max_output_bytes: int,
    media_type: str,
    audio_format: str | None = None,
) -> Path:
    candidates = [
        path
        for path in job_dir.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.casefold()
        in (AUDIO_SUFFIXES if media_type in {"audio", "document"} else VIDEO_SUFFIXES)
    ]
    if not candidates:
        raise DownloadError("output_missing")
    if media_type in {"audio", "document"}:
        expected_suffix = _audio_output_suffix(audio_format)
        audio_candidates = [
            path for path in candidates if path.suffix.casefold() == expected_suffix
        ]
        if not audio_candidates:
            raise DownloadError("output_format")
        candidates = audio_candidates
    output = max(candidates, key=lambda path: path.stat().st_size)
    size = output.stat().st_size
    if size <= 0:
        raise DownloadError("output_empty")
    if size > max_output_bytes:
        raise DownloadError("output_limit")
    return output


def _validated_best_transfer_url(inspection, option, settings) -> str:
    candidate = getattr(inspection, "best_available", None)
    if (
        candidate is None
        or option.size_bytes is None
        or option.size_bytes > settings.max_upload_bytes
        or candidate.size_bytes != option.size_bytes
        or candidate.size_bytes > settings.max_upload_bytes
    ):
        raise DownloadError("output_limit")
    domains = getattr(candidate, "validation_domains", settings.allowed_domains)
    if not domains:
        raise DownloadError("source_download_failed")
    validate_source_url(candidate.url, domains)
    current_size = probe_exact_video_size(candidate.url)
    if current_size is None:
        raise DownloadError("source_download_failed")
    if current_size > settings.max_upload_bytes:
        raise DownloadError("output_limit")
    if current_size != candidate.size_bytes:
        raise DownloadError("source_download_failed")
    return candidate.url


def _validated_transfer_url(record, option, settings) -> str:
    inspection = record.inspection
    source_url = inspection.url
    validate_source_url(source_url, settings.allowed_domains)
    if option.key == BEST_AVAILABLE_KEY:
        return _validated_best_transfer_url(inspection, option, settings)

    transfer_url = getattr(inspection, "download_url", None) or source_url
    if transfer_url == source_url:
        return transfer_url
    if is_pmvhaven_url(source_url):
        validate_source_url(transfer_url, PMVHAVEN_MEDIA_DOMAINS)
        return transfer_url
    adapter = adapter_for_url(source_url)
    if adapter is None or not adapter.owns_transfer_url(source_url, transfer_url):
        raise DownloadError("source_download_failed")
    validate_source_url(transfer_url, settings.allowed_domains)
    return transfer_url


# pylint: disable=too-many-arguments
def download_media(
    record,
    option,
    settings,
    cancel_event: threading.Event,
    *,
    progress_callback: Callable[[DownloadProgress], None] | None = None,
    preparing_callback: Callable[[], None] | None = None,
) -> DownloadedMedia:
    """Download one claimed job into a private directory and validate its output."""

    job_root = settings.job_root
    job_dir = job_root / record.job_id
    try:
        if cancel_event.is_set():
            raise DownloadCancelled()
        transfer_url = _validated_transfer_url(record, option, settings)
        job_root.mkdir(parents=True, exist_ok=True)
        job_dir.mkdir()
        if not _disk_has_reserve(
            job_root, settings.disk_reserve_bytes, settings.max_upload_bytes
        ):
            raise DownloadError("disk_space")

        import yt_dlp  # pylint: disable=import-outside-toplevel

        try:
            with yt_dlp.YoutubeDL(
                _ydl_options(
                    transfer_url,
                    option,
                    job_dir,
                    settings,
                    cancel_event,
                    progress_callback,
                    preparing_callback,
                )
            ) as ydl:
                ydl.download([transfer_url])
        except yt_dlp.utils.DownloadError as error:
            if cancel_event.is_set():
                raise DownloadCancelled() from error
            raise DownloadError("source_download_failed") from error
        if cancel_event.is_set():
            raise DownloadCancelled()
        return DownloadedMedia(
            path=_validated_output(
                job_dir,
                settings.max_upload_bytes,
                option.media_type,
                option.audio_format,
            ),
            media_type=option.media_type,
        )
    except DownloadError:
        cleanup_job_directory(job_root, record.job_id)
        raise
    except (OSError, TypeError, ValueError) as error:
        cleanup_job_directory(job_root, record.job_id)
        raise DownloadError("download_failed") from error


# pylint: disable=too-many-instance-attributes
class DownloadManager:
    """Coordinate bounded worker-thread downloads and path-based uploads."""

    def __init__(
        self,
        jobs,
        settings,
        metadata_store: JobMetadataStore | None = None,
        *,
        delivery: DeliveryTransport | None = None,
        admission=None,
    ):
        self._jobs = jobs
        self._settings = settings
        self._metadata_store = metadata_store
        self._delivery = delivery or TelegramDeliveryTransport(
            local_mode=settings.local_mode,
            timeout_seconds=settings.upload_timeout_seconds,
        )
        self._admission = admission
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
        self._controls: dict[str, threading.Event] = {}
        self._retained_cleanup_tasks: set[asyncio.Task[None]] = set()

    async def _cleanup_retained_job(self, job_id: str, delay_seconds: float) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            cleanup_job_directory(self._settings.job_root, job_id)
        except (OSError, ValueError) as error:
            logger.warning(
                "Could not clean retained upload directory: %s",
                type(error).__name__,
            )

    def _schedule_retained_cleanup(
        self, job_id: str, delay_seconds: float | None = None
    ) -> None:
        delay = (
            self._settings.unconfirmed_upload_retention_seconds
            if delay_seconds is None
            else delay_seconds
        )
        task = asyncio.create_task(self._cleanup_retained_job(job_id, delay))
        self._retained_cleanup_tasks.add(task)
        task.add_done_callback(self._retained_cleanup_tasks.discard)

    def resume_retained_cleanups(self) -> None:
        """Resume expiry timers for ambiguous local uploads after a restart."""

        for job_id, delay in retained_upload_cleanup_delays(
            self._settings.job_root,
            retention_seconds=(self._settings.unconfirmed_upload_retention_seconds),
        ):
            self._schedule_retained_cleanup(job_id, delay)

    def _record_terminal_metadata(
        self,
        record,
        *,
        status: str,
        output_size: int | None,
        error_code: str | None,
    ) -> None:
        """Best-effort terminal metadata that never changes job delivery."""

        if self._metadata_store is None:
            return
        try:
            self._metadata_store.record_terminal(
                record,
                status=status,
                temp_dir=self._settings.job_root / record.job_id,
                output_size=output_size,
                error_code=error_code,
            )
        except (OSError, sqlite3.Error) as error:
            logger.warning(
                "Could not record terminal job metadata: %s",
                type(error).__name__,
            )

    # This is the single job-lifecycle boundary: worker, upload, cancellation,
    # cleanup, and terminal metadata must remain ordered in one coroutine.
    # pylint: disable=too-many-branches,too-many-statements,too-many-locals
    # pylint: disable=too-many-arguments
    async def run(
        self,
        record,
        option,
        message,
        progress_reporter: TelegramProgressReporter | None = None,
    ) -> None:
        """Run one claimed job and expire its private working directory."""

        cancel_event = threading.Event()
        worker_task: asyncio.Task | None = None
        terminal_status = "failed"
        output_size: int | None = None
        error_code: str | None = "download_failed"
        phase_recorder = JobPhaseRecorder(record.job_id)
        queue_released = False
        self._controls[record.job_id] = cancel_event
        try:
            phase_recorder.start("queue")
            async with self._semaphore:
                if self._admission is not None:
                    self._admission.leave_queue(record.job_id)
                    queue_released = True
                phase_recorder.finish()
                current = self._jobs.get_for_user(
                    record.job_id, record.user_id, record.chat_id
                )
                if current is None or current.status == "cancelled":
                    raise DownloadCancelled()
                self._jobs.set_status(record.job_id, "downloading")
                if progress_reporter is not None:
                    await progress_reporter.start()
                phase_recorder.start("download")
                worker_kwargs: dict[str, object] = {}
                if progress_reporter is not None:
                    worker_kwargs = {
                        "progress_callback": progress_reporter.publish_from_worker,
                        "preparing_callback": progress_reporter.show_preparing_from_worker,
                    }
                worker_task = asyncio.create_task(
                    asyncio.to_thread(
                        download_media,
                        record,
                        option,
                        self._settings,
                        cancel_event,
                        **worker_kwargs,
                    )
                )
                try:
                    media = await asyncio.wait_for(
                        asyncio.shield(worker_task),
                        timeout=self._settings.download_timeout_seconds,
                    )
                except TimeoutError as error:
                    cancel_event.set()
                    try:
                        await worker_task
                    except DownloadError as worker_error:
                        logger.debug(
                            "Timed-out download worker ended with %s",
                            type(worker_error).__name__,
                        )
                    raise DownloadError("download_timeout") from error
                if cancel_event.is_set():
                    raise DownloadCancelled()
                output_size = media.path.stat().st_size
                phase_recorder.finish(byte_count=output_size)
                self._jobs.set_status(record.job_id, "uploading")
                if progress_reporter is not None:
                    await progress_reporter.show_preparing()
                    await progress_reporter.show_uploading()
                try:
                    phase_recorder.start("upload")
                    await self._delivery.deliver(message, media)
                    phase_recorder.finish(byte_count=output_size)
                except DeliveryError as error:
                    raise DownloadError(error.code) from error
            terminal_status = "completed"
            error_code = None
        except DownloadCancelled:
            phase_recorder.fail_active("cancelled")
            terminal_status = "cancelled"
            error_code = "cancelled"
            raise
        except DownloadError as error:
            phase_recorder.fail_active(error.code)
            error_code = error.code
            raise
        except asyncio.CancelledError:
            phase_recorder.fail_active("cancelled")
            terminal_status = "cancelled"
            error_code = "cancelled"
            cancel_event.set()
            if worker_task is not None and not worker_task.done():
                try:
                    await asyncio.shield(worker_task)
                except DownloadError as worker_error:
                    logger.debug(
                        "Cancelled download worker ended with %s",
                        type(worker_error).__name__,
                    )
            raise
        finally:
            if self._admission is not None and not queue_released:
                self._admission.leave_queue(record.job_id)
            phase_recorder.fail_active(error_code or terminal_status)
            phase_recorder.start("cleanup")
            cleanup_succeeded = False
            retain_for_server = (
                self._settings.local_mode and error_code == "upload_unconfirmed"
            )
            try:
                if progress_reporter is not None:
                    await progress_reporter.stop()
            finally:
                try:
                    if retain_for_server:
                        try:
                            _mark_unconfirmed_upload(
                                self._settings.job_root, record.job_id
                            )
                        except (OSError, ValueError) as marker_error:
                            logger.warning(
                                "Could not mark retained upload directory: %s",
                                type(marker_error).__name__,
                            )
                        self._schedule_retained_cleanup(record.job_id)
                    else:
                        cleanup_job_directory(self._settings.job_root, record.job_id)
                finally:
                    try:
                        self._record_terminal_metadata(
                            record,
                            status=terminal_status,
                            output_size=output_size,
                            error_code=error_code,
                        )
                    finally:
                        self._jobs.remove(record.job_id)
                        self._controls.pop(record.job_id, None)
                        cleanup_succeeded = True
            if cleanup_succeeded:
                phase_recorder.finish(
                    outcome="retained" if retain_for_server else terminal_status
                )
            else:
                phase_recorder.fail_active("cleanup_failed")

    def cancel_for_user(self, user_id: int, chat_id: int) -> bool:
        """Request cancellation for the user's queued or downloading job."""

        record = self._jobs.active_for_user(user_id, chat_id)
        if record is None or record.status == "uploading":
            return False
        cancelled = self._jobs.cancel_for_user(record.job_id, user_id, chat_id)
        if cancelled:
            control = self._controls.get(record.job_id)
            if control is not None:
                control.set()
        return cancelled
