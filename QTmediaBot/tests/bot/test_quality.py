from qtmedia_bot.bot.services.quality import (
    build_quality_options,
    format_size,
)


def test_quality_catalog_deduplicates_heights_and_omits_known_over_cap_formats():
    info = {
        "formats": [
            {
                "format_id": "1080-av",
                "height": 1080,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "filesize": 3_000_000,
                "tbr": 1000,
            },
            {
                "format_id": "1080-video",
                "height": 1080,
                "vcodec": "avc1",
                "acodec": "none",
                "filesize": 2_000_000,
                "tbr": 1200,
            },
            {
                "format_id": "720-video",
                "height": 720,
                "vcodec": "avc1",
                "acodec": "none",
                "filesize": 2_000_000,
            },
            {
                "format_id": "480-video",
                "height": 480,
                "vcodec": "avc1",
                "acodec": "none",
                "filesize": 6_000_000,
            },
            {
                "format_id": "audio",
                "vcodec": "none",
                "acodec": "mp4a",
                "filesize": 500_000,
            },
        ]
    }

    options = build_quality_options(info, max_output_bytes=4_000_000)
    keys = [option.key for option in options]

    assert keys == ["v1080", "v720", "mp3", "m4a", "flac", "alac"]
    assert options[0].format_selector == "1080-av"
    assert options[1].format_selector == "720-video+bestaudio/best"
    assert options[2].media_type == "audio"
    assert options[2].audio_format == "mp3"
    assert options[3].audio_format == "m4a"
    assert options[4].media_type == "document"
    assert options[4].audio_format == "flac"
    assert options[5].audio_format == "alac"


def test_quality_catalog_preserves_unknown_size_and_marks_approximate_size():
    info = {
        "formats": [
            {
                "format_id": "unknown",
                "height": 360,
                "vcodec": "avc1",
                "acodec": "mp4a",
            },
            {
                "format_id": "audio-approx",
                "vcodec": "none",
                "acodec": "mp4a",
                "filesize_approx": 1_500_000,
            },
        ]
    }

    options = build_quality_options(info, max_output_bytes=2_000_000)

    assert options[0].size_bytes is None
    assert (
        format_size(options[0].size_bytes, options[0].size_approximate)
        == "size unknown"
    )
    assert options[1].size_approximate is True
    assert format_size(options[1].size_bytes, options[1].size_approximate) == "~1.4 MB"


def test_quality_catalog_offers_playable_and_lossless_audio_choices():
    options = build_quality_options(
        {
            "duration": 60,
            "formats": [
                {
                    "format_id": "audio",
                    "vcodec": "none",
                    "acodec": "opus",
                    "filesize": 1_000_000,
                }
            ],
        },
        max_output_bytes=2_000_000,
    )

    assert [option.key for option in options] == ["mp3", "m4a", "flac", "alac"]
    assert options[0].size_bytes == 1_440_000
    assert options[0].size_approximate is True
    assert options[1].size_bytes == 1_920_000
    assert options[1].size_approximate is True
    assert options[2].size_bytes is None
    assert options[2].media_type == "document"
    assert options[3].media_type == "document"


def test_quality_catalog_accepts_height_bearing_video_without_codec_labels():
    options = build_quality_options(
        {
            "formats": [
                {
                    "format_id": "720-direct",
                    "url": "https://cdn.example/video-720.mp4",
                    "height": 720,
                    "filesize": 1_500_000,
                },
                {
                    "format_id": "audio",
                    "url": "https://cdn.example/audio.m4a",
                    "vcodec": "none",
                    "acodec": "mp4a",
                    "filesize": 250_000,
                },
            ]
        },
        max_output_bytes=2_000_000,
    )

    assert [option.key for option in options] == [
        "v720",
        "mp3",
        "m4a",
        "flac",
        "alac",
    ]
    assert options[0].format_selector == "720-direct"


def test_quality_catalog_prefers_non_hls_format_when_quality_is_equal():
    info = {
        "formats": [
            {
                "format_id": "hls-720",
                "height": 720,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "protocol": "m3u8_native",
                "filesize": 1_000_000,
                "tbr": 1000,
            },
            {
                "format_id": "dash-720",
                "height": 720,
                "vcodec": "avc1",
                "acodec": "none",
                "protocol": "https",
                "filesize": 1_000_000,
                "tbr": 900,
            },
        ]
    }

    options = build_quality_options(info, max_output_bytes=2_000_000)

    assert options[0].format_selector == "dash-720+bestaudio/best"


def test_quality_catalog_offers_exact_under_cap_best_fallback_when_empty():
    options = build_quality_options(
        {"formats": []},
        max_output_bytes=2_000_000,
        best_available_size_bytes=1_500_000,
    )

    assert len(options) == 1
    assert options[0].key == "best"
    assert options[0].label == "Best available"
    assert options[0].size_bytes == 1_500_000
    assert options[0].size_approximate is False
    assert options[0].format_selector == "bestvideo+bestaudio/best"
    assert options[0].media_type == "video"


def test_quality_catalog_omits_unknown_or_over_cap_best_fallback():
    assert (
        build_quality_options(
            {"formats": []},
            max_output_bytes=2_000_000,
            best_available_size_bytes=None,
        )
        == ()
    )
    assert (
        build_quality_options(
            {"formats": []},
            max_output_bytes=2_000_000,
            best_available_size_bytes=2_000_001,
        )
        == ()
    )


def test_quality_catalog_does_not_append_best_fallback_to_normal_options():
    options = build_quality_options(
        {
            "formats": [
                {
                    "format_id": "720",
                    "height": 720,
                    "vcodec": "avc1",
                    "acodec": "mp4a",
                    "filesize": 1_000_000,
                }
            ]
        },
        max_output_bytes=2_000_000,
        best_available_size_bytes=1_500_000,
    )

    assert [option.key for option in options] == ["v720"]

