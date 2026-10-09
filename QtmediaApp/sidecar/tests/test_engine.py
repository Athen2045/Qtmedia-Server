from __future__ import annotations

import threading
from pathlib import Path

from qtmedia.desktop_service.models import (
    DownloadResult,
    FormatOption,
    InspectedMedia,
    Inspection,
    InspectionResult,
)
from qtmedia_engine.engine import Engine
from qtmedia_engine.protocol import Request


def test_engine_probe_emits_ready(tmp_path: Path):
    events: list[dict[str, object]] = []
    engine = Engine(tmp_path, emit=events.append)

    engine.handle(Request("probe", "probe", {}))

    assert events == [{"id": "probe", "event": "ready"}]


def test_engine_inspection_stores_opaque_media_and_emits_safe_result(tmp_path: Path):
    events: list[dict[str, object]] = []
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Safe title",
        site="XVideos",
        thumbnail_url="https://images.invalid/poster.jpg",
        duration_seconds=120,
        formats=(FormatOption("video", "Video", "mp4"),),
    )
    inspection = Inspection(
        media=media,
        result=InspectionResult("Safe title", "XVideos", 120, media.formats),
    )
    engine = Engine(
        tmp_path,
        emit=events.append,
        inspector=lambda _url, _policy: inspection,
    )

    engine.handle(
        Request(
            "r1",
            "inspect",
            {"url": "https://www.xvideos.com/video.abc/title"},
        )
    )

    assert events[0] == {"id": "r1", "event": "inspection_started"}
    assert events[1]["media_id"] == "media-1"
    assert events[1]["formats"][0]["kind"] == "video"
    assert "url" not in events[1]
    assert "thumbnail_url" not in events[1]
    assert engine.session.get_media("media-1") == media


def test_engine_emits_provider_unavailable_without_raw_failure_details(tmp_path: Path):
    events: list[dict[str, object]] = []
    engine = Engine(
        tmp_path,
        emit=events.append,
        inspector=lambda _url, _policy: (_ for _ in ()).throw(ValueError("provider_unavailable")),
    )

    engine.handle(Request("r1", "inspect", {"url": "https://www.xvideos.com/video.abc/title"}))

    assert events == [
        {"id": "r1", "event": "inspection_started"},
        {"id": "r1", "event": "error", "code": "provider_unavailable"},
    ]


def test_engine_download_emits_progress_completion_and_library_change(tmp_path: Path):
    events: list[dict[str, object]] = []
    finished = threading.Event()
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Safe title",
        site="XVideos",
        thumbnail_url=None,
        formats=(FormatOption("audio", "Audio", "mp3"),),
    )

    def downloader(_media, _kind, _library, progress, _cancel):
        from qtmedia.desktop_service.models import DownloadProgress

        progress(DownloadProgress(5, 10, 50.0))
        finished.set()
        return DownloadResult("audio/Safe title [media-1].mp3", "Safe title", "audio", "mp3")

    engine = Engine(tmp_path, emit=events.append, downloader=downloader)
    engine.session.store_media(media)

    engine.handle(Request("r2", "download", {"media_id": "media-1", "format_key": "audio"}))
    assert finished.wait(timeout=2)
    engine.join_jobs(timeout=2)

    assert [event["event"] for event in events] == [
        "download_started",
        "download_progress",
        "download_completed",
        "library_changed",
    ]
    assert events[1]["percent"] == 50.0
    assert events[2]["entry"]["relative_path"].startswith("audio/")


def test_engine_cancel_acknowledges_request_before_worker_confirms_stop(tmp_path: Path):
    events: list[dict[str, object]] = []
    engine = Engine(tmp_path, emit=events.append)
    cancel = threading.Event()
    engine.session.register_job("job-opaque", cancel)

    engine.handle(Request("cancel-1", "cancel", {"job_id": "job-opaque"}))

    assert cancel.is_set()
    assert events == [
        {"id": "cancel-1", "event": "cancellation_requested", "job_id": "job-opaque"}
    ]
