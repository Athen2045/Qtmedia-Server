"""Sidecar request dispatcher and asynchronous download orchestration."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qtmedia.desktop_service.download import (
    DesktopDownloadCancelled,
    download_media,
)
from qtmedia.desktop_service.inspection import inspect_url
from qtmedia.desktop_service.models import DownloadProgress, MediaLibrary
from qtmedia.desktop_service.policy import AdapterPolicy, DesktopPolicyError

from .library import scan_library
from .protocol import Request
from .session import SessionCatalog, SessionError

EventSink = Callable[[dict[str, Any]], None]


class Engine:
    def __init__(
        self,
        library_root: Path,
        *,
        emit: EventSink,
        inspector=inspect_url,
        downloader=download_media,
    ) -> None:
        self.library = MediaLibrary.create(library_root)
        self.emit = emit
        self.inspector = inspector
        self.downloader = downloader
        self.policy = AdapterPolicy()
        self.session = SessionCatalog()
        self._threads: dict[str, threading.Thread] = {}
        self._threads_lock = threading.Lock()

    def _event(self, request_id: str, event: str, **payload: Any) -> None:
        self.emit({"id": request_id, "event": event, **payload})

    def handle(self, request: Request) -> None:
        try:
            if request.action == "probe":
                self._event(request.request_id, "ready")
            elif request.action == "inspect":
                self._inspect(request)
            elif request.action == "download":
                self._download(request)
            elif request.action == "cancel":
                self._cancel(request)
            elif request.action == "library_list":
                entries = [entry.as_dict() for entry in scan_library(self.library.root)]
                self._event(request.request_id, "library_changed", entries=entries)
        except DesktopPolicyError as error:
            self._event(request.request_id, "error", code=error.code)
        except SessionError as error:
            self._event(request.request_id, "error", code=str(error))
        except ValueError as error:
            code = str(error) if str(error) in {"no_formats", "format_unavailable", "provider_unavailable"} else "invalid_request"
            self._event(request.request_id, "error", code=code)
        except Exception:  # protocol output must not expose provider details
            self._event(request.request_id, "error", code="operation_failed")

    def _inspect(self, request: Request) -> None:
        self._event(request.request_id, "inspection_started")
        inspection = self.inspector(str(request.payload["url"]), self.policy)
        self.session.store_media(inspection.media)
        self._event(
            request.request_id,
            "inspection_ready",
            media_id=inspection.media.media_id,
            **inspection.result.as_dict(),
        )

    def _download(self, request: Request) -> None:
        media = self.session.get_media(str(request.payload["media_id"]))
        format_key = str(request.payload["format_key"])
        job_id = f"job-{secrets.token_urlsafe(9)}"
        cancel = threading.Event()
        self.session.register_job(job_id, cancel)
        self._event(request.request_id, "download_started", job_id=job_id)
        thread = threading.Thread(
            target=self._run_download,
            args=(request.request_id, job_id, media, format_key, cancel),
            name=f"qtmedia-{job_id}",
            daemon=True,
        )
        with self._threads_lock:
            self._threads[job_id] = thread
        thread.start()

    def _run_download(self, request_id, job_id, media, format_key, cancel) -> None:
        def progress(event: DownloadProgress) -> None:
            self._event(
                request_id,
                "download_progress",
                job_id=job_id,
                **event.as_dict(),
            )

        try:
            result = self.downloader(media, format_key, self.library, progress, cancel)
            self._event(
                request_id,
                "download_completed",
                job_id=job_id,
                entry=result.as_dict(),
            )
            self._event(request_id, "library_changed")
        except DesktopDownloadCancelled:
            self._event(request_id, "download_cancelled", job_id=job_id)
        except Exception:
            self._event(request_id, "error", code="download_failed", job_id=job_id)
        finally:
            self.session.remove_job(job_id)
            with self._threads_lock:
                self._threads.pop(job_id, None)

    def _cancel(self, request: Request) -> None:
        job_id = str(request.payload["job_id"])
        self.session.cancel_job(job_id)
        self._event(request.request_id, "cancellation_requested", job_id=job_id)

    def join_jobs(self, timeout: float | None = None) -> None:
        with self._threads_lock:
            threads = tuple(self._threads.values())
        for thread in threads:
            thread.join(timeout=timeout)

    def shutdown(self) -> None:
        self.session.cancel_all()
        self.join_jobs(timeout=5)
