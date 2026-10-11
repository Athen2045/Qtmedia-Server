//! Planning how library videos become playable (no FFmpeg needed).

use std::path::Path;

use qtmedia_app::paths::{resolve_library_entry, VIDEO_EXTENSIONS};
use qtmedia_app::playback::{
    cache_name, ffmpeg_args, is_cache_file_name, parse_probe, parse_progress, plan, Encoder, Plan,
    PlanError, Probe, StreamInfo, Support,
};

const NO_DOLBY: Support = Support { dolby: false };
const DOLBY: Support = Support { dolby: true };

fn stream(codec: &str) -> Option<StreamInfo> {
    Some(StreamInfo {
        codec: codec.into(),
        pix_fmt: Some("yuv420p".into()),
        channels: Some(2),
    })
}

fn probe(video: &str, audio: Option<&str>) -> Probe {
    Probe {
        video: stream(video),
        audio: audio.and_then(stream),
        duration_seconds: Some(120.0),
    }
}

#[test]
fn reads_ffprobe_json_and_skips_cover_art() {
    let json = r#"{
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
            {"index": 1, "codec_type": "video", "codec_name": "H264", "pix_fmt": "yuv420p", "disposition": {"attached_pic": 0}},
            {"index": 2, "codec_type": "audio", "codec_name": "ac3", "channels": 6, "disposition": {}},
            {"index": 3, "codec_type": "subtitle", "codec_name": "subrip"}
        ],
        "format": {"format_name": "matroska,webm", "duration": "5400.250000"}
    }"#;
    let probe = parse_probe(json).unwrap();
    assert_eq!(probe.video.as_ref().unwrap().codec, "h264");
    assert_eq!(probe.audio.as_ref().unwrap().codec, "ac3");
    assert_eq!(probe.audio.as_ref().unwrap().channels, Some(6));
    assert_eq!(probe.duration_seconds, Some(5400.25));
    assert!(parse_probe("not json").is_none());
}

#[test]
fn plays_what_the_webview_supports_and_converts_the_rest() {
    // Direct: MP4/M4V/WebM with supported codecs.
    assert_eq!(
        plan("mp4", &probe("h264", Some("aac")), NO_DOLBY),
        Ok(Plan::Direct)
    );
    assert_eq!(
        plan("mp4", &probe("vp9", Some("opus")), NO_DOLBY),
        Ok(Plan::Direct)
    );
    assert_eq!(
        plan("m4v", &probe("hevc", Some("aac")), NO_DOLBY),
        Ok(Plan::Direct)
    );
    assert_eq!(
        plan("webm", &probe("vp9", Some("opus")), NO_DOLBY),
        Ok(Plan::Direct)
    );
    assert_eq!(
        plan("webm", &probe("av1", None), NO_DOLBY),
        Ok(Plan::Direct)
    );

    // Remux: fine codecs in another container.
    assert_eq!(
        plan("mkv", &probe("h264", Some("aac")), NO_DOLBY),
        Ok(Plan::Remux)
    );
    assert_eq!(
        plan("mov", &probe("h264", Some("aac")), NO_DOLBY),
        Ok(Plan::Remux)
    );
    assert_eq!(
        plan("mkv", &probe("hevc", Some("flac")), NO_DOLBY),
        Ok(Plan::Remux)
    );
    assert_eq!(
        plan("avi", &probe("h264", Some("mp3")), NO_DOLBY),
        Ok(Plan::Remux)
    );

    // Transcode only what needs it.
    assert_eq!(
        plan("mkv", &probe("h264", Some("ac3")), NO_DOLBY),
        Ok(Plan::Transcode {
            video: false,
            audio: true
        })
    );
    assert_eq!(
        plan("mkv", &probe("h264", Some("dts")), NO_DOLBY),
        Ok(Plan::Transcode {
            video: false,
            audio: true
        })
    );
    assert_eq!(
        plan("mp4", &probe("h264", Some("eac3")), NO_DOLBY),
        Ok(Plan::Transcode {
            video: false,
            audio: true
        })
    );
    assert_eq!(
        plan("avi", &probe("mpeg4", Some("mp3")), NO_DOLBY),
        Ok(Plan::Transcode {
            video: true,
            audio: false
        })
    );
    assert_eq!(
        plan("mov", &probe("prores", Some("pcm_s16le")), NO_DOLBY),
        Ok(Plan::Transcode {
            video: true,
            audio: true
        })
    );
    assert_eq!(
        plan("mkv", &probe("mpeg2video", None), NO_DOLBY),
        Ok(Plan::Transcode {
            video: true,
            audio: false
        })
    );
    // Vorbis is fine in WebM but not in MP4; VP8 is fine in WebM but not MP4.
    assert_eq!(
        plan("mkv", &probe("vp9", Some("vorbis")), NO_DOLBY),
        Ok(Plan::Transcode {
            video: false,
            audio: true
        })
    );
    assert_eq!(
        plan("mkv", &probe("vp8", Some("opus")), NO_DOLBY),
        Ok(Plan::Transcode {
            video: true,
            audio: false
        })
    );

    // 10-bit H.264 has no hardware decoder in the webview.
    let mut hi10 = probe("h264", Some("aac"));
    hi10.video.as_mut().unwrap().pix_fmt = Some("yuv420p10le".into());
    assert_eq!(
        plan("mkv", &hi10, NO_DOLBY),
        Ok(Plan::Transcode {
            video: true,
            audio: false
        })
    );

    assert_eq!(
        plan(
            "mkv",
            &Probe {
                video: None,
                ..probe("h264", Some("aac"))
            },
            NO_DOLBY
        ),
        Err(PlanError::NoVideo)
    );
}

fn joined(args: &[std::ffi::OsString]) -> String {
    args.iter()
        .map(|arg| arg.to_string_lossy())
        .collect::<Vec<_>>()
        .join(" ")
}

#[test]
fn ffmpeg_copies_what_it_can_and_encodes_only_what_it_must() {
    let input = Path::new("in.mkv");
    let output = Path::new("out.mp4.part");
    let remux = joined(&ffmpeg_args(
        input,
        output,
        Plan::Remux,
        &probe("hevc", Some("aac")),
        Encoder::Nvenc,
    ));
    assert!(remux.contains("-map 0:v:0 -map 0:a:0? -sn -dn"), "{remux}");
    assert!(remux.contains("-c:v copy -tag:v hvc1"), "{remux}");
    assert!(remux.contains("-c:a copy"), "{remux}");
    assert!(
        remux.contains("-movflags +faststart -f mp4 -progress pipe:1"),
        "{remux}"
    );
    assert!(remux.ends_with("out.mp4.part"), "{remux}");

    let audio = joined(&ffmpeg_args(
        input,
        output,
        Plan::Transcode {
            video: false,
            audio: true,
        },
        &probe("h264", Some("ac3")),
        Encoder::Nvenc,
    ));
    assert!(
        audio.contains("-c:v copy") && audio.contains("-c:a libopus -b:a 192k -ac 2"),
        "{audio}"
    );
    assert!(!audio.contains("nvenc"), "{audio}");

    let nvenc = joined(&ffmpeg_args(
        input,
        output,
        Plan::Transcode {
            video: true,
            audio: false,
        },
        &probe("mpeg4", Some("mp3")),
        Encoder::Nvenc,
    ));
    assert!(
        nvenc.contains("-c:v h264_nvenc")
            && nvenc.contains("-pix_fmt yuv420p")
            && nvenc.contains("-c:a copy"),
        "{nvenc}"
    );
    let x264 = joined(&ffmpeg_args(
        input,
        output,
        Plan::Transcode {
            video: true,
            audio: false,
        },
        &probe("mpeg4", None),
        Encoder::X264,
    ));
    assert!(
        x264.contains("-c:v libx264 -preset veryfast -crf 18"),
        "{x264}"
    );
    assert!(
        !x264.contains("-c:a"),
        "no audio stream, no audio codec: {x264}"
    );
}

#[test]
fn cache_names_change_with_the_file_and_are_strictly_checked() {
    let a = cache_name("video/Film.mkv", 1000, 42);
    assert_eq!(a.len(), 16);
    assert_eq!(a, cache_name("video/Film.mkv", 1000, 42));
    assert_ne!(a, cache_name("video/Film.mkv", 1001, 42));
    assert_ne!(a, cache_name("video/Film.mkv", 1000, 43));
    assert_ne!(a, cache_name("video/Other.mkv", 1000, 42));
    assert!(is_cache_file_name(&format!("{a}.mp4")));
    for bad in [
        "../x.mp4",
        "0123456789abcdef.mkv",
        "0123456789ABCDEF.mp4",
        "0123456789abcde.mp4",
        "0123456789abcdef.mp4/..",
        "",
    ] {
        assert!(!is_cache_file_name(bad), "{bad}");
    }
}

#[test]
fn progress_comes_from_out_time() {
    assert_eq!(
        parse_progress("out_time_us=60000000", Some(120.0)),
        Some(50.0)
    );
    assert_eq!(
        parse_progress("out_time_us=999000000", Some(120.0)),
        Some(99.9)
    );
    assert_eq!(parse_progress("progress=continue", Some(120.0)), None);
    assert_eq!(parse_progress("out_time_us=N/A", Some(120.0)), None);
    assert_eq!(parse_progress("out_time_us=1000", None), None);
}

#[test]
fn the_library_accepts_the_new_video_formats_only_under_video() {
    let dir = tempfile::tempdir().unwrap();
    for sub in ["audio", "video"] {
        std::fs::create_dir_all(dir.path().join(sub)).unwrap();
    }
    for extension in VIDEO_EXTENSIONS {
        std::fs::write(dir.path().join(format!("video/Clip.{extension}")), b"x").unwrap();
        assert!(
            resolve_library_entry(dir.path(), &format!("video/Clip.{extension}")).is_ok(),
            "{extension}"
        );
        std::fs::write(dir.path().join(format!("audio/Clip.{extension}")), b"x").unwrap();
        assert!(
            resolve_library_entry(dir.path(), &format!("audio/Clip.{extension}")).is_err(),
            "{extension}"
        );
    }
    std::fs::write(dir.path().join("video/Clip.exe"), b"x").unwrap();
    assert!(resolve_library_entry(dir.path(), "video/Clip.exe").is_err());
}

#[test]
fn dolby_plays_as_it_is_where_windows_decodes_it() {
    // With the Windows Dolby decoder: AC-3/E-AC-3 are copied, not converted.
    assert_eq!(
        plan("mp4", &probe("h264", Some("eac3")), DOLBY),
        Ok(Plan::Direct)
    );
    assert_eq!(
        plan("mkv", &probe("h264", Some("ac3")), DOLBY),
        Ok(Plan::Remux)
    );
    // Without it, they are converted (keeping the channel count).
    assert_eq!(
        plan("mkv", &probe("h264", Some("ac3")), NO_DOLBY),
        Ok(Plan::Transcode {
            video: false,
            audio: true
        })
    );
    // DTS and TrueHD have no webview decoder either way.
    assert_eq!(
        plan("mkv", &probe("h264", Some("dts")), DOLBY),
        Ok(Plan::Transcode {
            video: false,
            audio: true
        })
    );
    assert_eq!(
        plan("mkv", &probe("hevc", Some("truehd")), DOLBY),
        Ok(Plan::Transcode {
            video: false,
            audio: true
        })
    );
}

#[test]
fn converted_surround_stays_surround() {
    let input = Path::new("in.mkv");
    let output = Path::new("out.mp4.part");
    let mut surround = probe("h264", Some("dts"));
    surround.audio.as_mut().unwrap().channels = Some(6);
    let args = joined(&ffmpeg_args(
        input,
        output,
        Plan::Transcode {
            video: false,
            audio: true,
        },
        &surround,
        Encoder::Nvenc,
    ));
    assert!(
        args.contains("-c:a libopus -mapping_family 1 -b:a 384k"),
        "{args}"
    );
    assert!(!args.contains("-ac 2"), "{args}");
    // DTS 5.1(side) is remapped to the layout Opus surround accepts.
    assert!(args.contains("-af aformat=channel_layouts=5.1"), "{args}");
    surround.audio.as_mut().unwrap().channels = Some(8);
    let args = joined(&ffmpeg_args(
        input,
        output,
        Plan::Transcode {
            video: false,
            audio: true,
        },
        &surround,
        Encoder::Nvenc,
    ));
    assert!(args.contains("-b:a 512k"), "{args}");
}
