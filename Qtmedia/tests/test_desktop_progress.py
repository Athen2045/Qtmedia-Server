from __future__ import annotations

import threading

import pytest

from qtmedia.desktop_service.download import (
    DesktopDownloadCancelled,
    _postprocessor_hook,
    _progress_hook,
    stream_count,
)
from qtmedia.desktop_service.models import DownloadProgress


def collect():
    events: list[DownloadProgress] = []
    return events, events.append


def downloading(filename, *, vcodec, acodec, downloaded, total=None, estimate=None, **extra):
    return {
        "status": "downloading",
        "filename": filename,
        "downloaded_bytes": downloaded,
        "total_bytes": total,
        "total_bytes_estimate": estimate,
        "info_dict": {"vcodec": vcodec, "acodec": acodec},
        **extra,
    }


def test_merged_downloads_report_each_stream_instead_of_a_restarting_bar():
    events, sink = collect()
    hook = _progress_hook(sink, threading.Event(), parts=2)

    hook(downloading("x.f137.mp4", vcodec="avc1", acodec="none", downloaded=50, total=100))
    hook(downloading("x.f137.mp4", vcodec="avc1", acodec="none", downloaded=100, total=100))
    hook(downloading("x.f140.m4a", vcodec="none", acodec="mp4a", downloaded=10, total=40))

    assert [(e.stage, e.stream, e.part, e.parts, e.percent) for e in events] == [
        ("downloading", "video", 1, 2, 50.0),
        ("downloading", "video", 1, 2, 100.0),
        ("downloading", "audio", 2, 2, 25.0),
    ]
    assert (events[-1].downloaded_bytes, events[-1].total_bytes) == (10, 40)


def test_single_stream_downloads_are_one_part():
    events, sink = collect()
    _progress_hook(sink, threading.Event(), parts=1)(
        downloading("x.mp4", vcodec="avc1", acodec="mp4a", downloaded=30, total=120)
    )

    assert (events[0].stream, events[0].part, events[0].parts, events[0].percent) == (None, 1, 1, 25.0)


def test_hls_progress_uses_fragments_when_the_size_is_only_estimated():
    events, sink = collect()
    _progress_hook(sink, threading.Event(), parts=1)(
        downloading("x.mp4", vcodec=None, acodec=None, downloaded=100, estimate=9000, fragment_index=3, fragment_count=10)
    )

    assert events[0].percent == 30.0
    assert events[0].total_bytes == 9000


def test_unknown_totals_report_bytes_without_a_percentage():
    events, sink = collect()
    _progress_hook(sink, threading.Event(), parts=1)(
        downloading("x.mp4", vcodec="avc1", acodec="mp4a", downloaded=500)
    )

    assert (events[0].percent, events[0].total_bytes, events[0].downloaded_bytes) == (None, None, 500)


@pytest.mark.parametrize(
    ("postprocessor", "stage"),
    [("Merger", "merging"), ("ExtractAudio", "converting"), ("FixupM3u8", "processing")],
)
def test_postprocessing_reports_what_ffmpeg_is_doing(postprocessor, stage):
    events, sink = collect()
    hook = _postprocessor_hook(sink, threading.Event())

    hook({"status": "started", "postprocessor": postprocessor})
    hook({"status": "finished", "postprocessor": postprocessor})

    assert [(e.stage, e.percent) for e in events] == [(stage, None)]


def test_instant_file_moves_are_not_reported_and_cancel_stops_postprocessing():
    events, sink = collect()
    cancel = threading.Event()
    hook = _postprocessor_hook(sink, cancel)

    hook({"status": "started", "postprocessor": "MoveFiles"})
    # Runs before the download starts; "Finishing up" there would be false.
    hook({"status": "started", "postprocessor": "ThumbnailsConvertor"})
    assert events == []

    cancel.set()
    with pytest.raises(DesktopDownloadCancelled):
        hook({"status": "started", "postprocessor": "Merger"})


@pytest.mark.parametrize(
    ("selector", "kind", "parts"),
    [("137+bestaudio[ext=m4a]", "video", 2), ("hls-1080p", "video", 1), ("251-drc", "audio", 1)],
)
def test_stream_count_follows_the_format_selector(selector, kind, parts):
    assert stream_count(selector, kind) == parts


def test_progress_serializes_the_new_fields():
    assert DownloadProgress(10, 40, 25.0, stage="downloading", stream="audio", part=2, parts=2).as_dict() == {
        "downloaded_bytes": 10,
        "total_bytes": 40,
        "percent": 25.0,
        "stage": "downloading",
        "stream": "audio",
        "part": 2,
        "parts": 2,
    }
    assert DownloadProgress.stage_only("saving").as_dict()["stage"] == "saving"


def test_download_reports_saving_after_the_transfer_and_registers_both_hooks(monkeypatch, tmp_path):
    import sys
    import types

    from qtmedia.desktop_service.download import build_download_options, download_media
    from qtmedia.desktop_service.models import (
        FormatOption,
        FormatSelection,
        InspectedMedia,
        MediaLibrary,
    )

    library = MediaLibrary.create(tmp_path / "library")
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Clip",
        site="XVideos",
        thumbnail_url=None,
        formats=(FormatOption("fmt-1", "1080p MP4", "mp4", "video", 1080),),
        selections={"fmt-1": FormatSelection("fmt-1", "video", "137+bestaudio[ext=m4a]", "mp4")},
    )
    options = build_download_options(media, "fmt-1", library, lambda _event: None, threading.Event())
    assert len(options["progress_hooks"]) == 1
    assert len(options["postprocessor_hooks"]) == 1

    class FakeYdl:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            self.opts["postprocessor_hooks"][0]({"status": "started", "postprocessor": "Merger"})
            (library.temp / "Clip [media-1].mp4").write_bytes(b"merged")
            return 0

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))
    events, sink = collect()

    download_media(media, "fmt-1", library, sink, threading.Event())

    assert [event.stage for event in events] == ["merging", "saving"]
