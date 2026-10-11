//! Making library videos playable in the webview (plan:
//! `docs/superpowers/plans/2026-10-11-video-formats.md`).
//!
//! WebView2 hardware-decodes H.264, HEVC, VP9 and AV1 with AAC, Opus, MP3 and
//! FLAC, in MP4 or WebM. A video that already fits plays directly. One with
//! fine codecs in another container (MKV, MOV, AVI) is **remuxed** into MP4,
//! with the streams copied unchanged. Anything else is **transcoded**, but only
//! the stream that needs it. Converted copies are cached, so each file is
//! prepared once.
//!
//! Everything here is pure (probe parsing, planning, FFmpeg arguments, cache
//! names, progress); `preparer.rs` runs the tools.

use std::ffi::OsString;
use std::path::Path;

use serde::Deserialize;

/// Bumped when the conversion recipe changes, so old copies are not reused.
const RECIPE_VERSION: u32 = 2;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct StreamInfo {
    pub codec: String,
    pub pix_fmt: Option<String>,
    pub channels: Option<u32>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Probe {
    pub video: Option<StreamInfo>,
    pub audio: Option<StreamInfo>,
    pub duration_seconds: Option<f64>,
}

#[derive(Deserialize)]
struct RawProbe {
    #[serde(default)]
    streams: Vec<RawStream>,
    format: Option<RawFormat>,
}

#[derive(Deserialize)]
struct RawStream {
    codec_type: Option<String>,
    codec_name: Option<String>,
    pix_fmt: Option<String>,
    channels: Option<u32>,
    #[serde(default)]
    disposition: RawDisposition,
}

#[derive(Deserialize, Default)]
struct RawDisposition {
    #[serde(default)]
    attached_pic: u8,
}

#[derive(Deserialize)]
struct RawFormat {
    duration: Option<String>,
}

/// Parses `ffprobe -show_streams -show_format -of json`. Cover-art "video"
/// streams (attached pictures) are ignored.
pub fn parse_probe(json: &str) -> Option<Probe> {
    let raw: RawProbe = serde_json::from_str(json).ok()?;
    let stream = |kind: &str| {
        raw.streams
            .iter()
            .find(|stream| {
                stream.codec_type.as_deref() == Some(kind) && stream.disposition.attached_pic == 0
            })
            .map(|stream| StreamInfo {
                codec: stream
                    .codec_name
                    .clone()
                    .unwrap_or_default()
                    .to_ascii_lowercase(),
                pix_fmt: stream.pix_fmt.clone(),
                channels: stream.channels,
            })
    };
    Some(Probe {
        video: stream("video"),
        audio: stream("audio"),
        duration_seconds: raw
            .format
            .and_then(|format| format.duration)
            .and_then(|value| value.parse().ok())
            .filter(|value: &f64| value.is_finite() && *value > 0.0),
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Plan {
    /// The webview plays the library file as it is.
    Direct,
    /// Copy the streams into an MP4 (seconds, no quality change).
    Remux,
    /// Re-encode the streams marked `true`; the others are copied.
    Transcode { video: bool, audio: bool },
}

impl Plan {
    pub fn label(self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::Remux => "remux",
            Self::Transcode { .. } => "transcode",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlanError {
    /// No video stream (e.g. an audio file renamed to .mkv).
    NoVideo,
}

/// Video the webview decodes in hardware. 10-bit H.264 (High 10) is not
/// supported by Chromium's decoders, so it is re-encoded.
fn video_playable(video: &StreamInfo) -> bool {
    let ten_bit_h264 = video.codec == "h264"
        && video.pix_fmt.as_deref().is_some_and(|format| {
            format.contains("10") || format.contains("422") || format.contains("444")
        });
    matches!(video.codec.as_str(), "h264" | "hevc" | "vp9" | "av1") && !ten_bit_h264
}

/// What the webview on this PC decodes beyond the always-present codecs.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Support {
    /// Dolby Digital (AC-3) and Dolby Digital Plus (E-AC-3), through the
    /// Windows Dolby decoder (absent on some editions).
    pub dolby: bool,
}

/// Audio the webview decodes from an MP4 (surround included).
fn audio_playable_in_mp4(audio: &StreamInfo, support: Support) -> bool {
    matches!(audio.codec.as_str(), "aac" | "opus" | "mp3" | "flac")
        || (support.dolby && matches!(audio.codec.as_str(), "ac3" | "eac3"))
}

/// How to make `extension` (lower case, no dot) with `probe` playable.
pub fn plan(extension: &str, probe: &Probe, support: Support) -> Result<Plan, PlanError> {
    let video = probe.video.as_ref().ok_or(PlanError::NoVideo)?;
    let video_ok = video_playable(video);
    let audio_ok = probe
        .audio
        .as_ref()
        .map_or(true, |audio| audio_playable_in_mp4(audio, support));
    let direct_container = match extension {
        "mp4" | "m4v" => video_ok && audio_ok,
        // WebM is VP8/VP9/AV1 with Opus/Vorbis by definition.
        "webm" => {
            matches!(video.codec.as_str(), "vp8" | "vp9" | "av1")
                && probe.audio.as_ref().map_or(true, |audio| {
                    matches!(audio.codec.as_str(), "opus" | "vorbis")
                })
        }
        _ => false,
    };
    if direct_container {
        return Ok(Plan::Direct);
    }
    if video_ok && audio_ok {
        return Ok(Plan::Remux);
    }
    Ok(Plan::Transcode {
        video: !video_ok,
        audio: !audio_ok,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Encoder {
    /// NVIDIA hardware encoder (fast; the user's RTX laptop).
    Nvenc,
    /// Software fallback.
    X264,
}

/// FFmpeg arguments that write `plan`'s MP4 to `output`, reporting progress
/// on stdout (`-progress pipe:1`).
pub fn ffmpeg_args(
    input: &Path,
    output: &Path,
    plan: Plan,
    probe: &Probe,
    encoder: Encoder,
) -> Vec<OsString> {
    let mut args: Vec<OsString> = ["-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i"]
        .iter()
        .map(OsString::from)
        .collect();
    args.push(input.as_os_str().to_owned());
    let mut push = |values: &[&str]| args.extend(values.iter().map(OsString::from));
    // First video and (if any) first audio stream; no subtitles or data.
    push(&["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]);
    let (video_encode, audio_encode) = match plan {
        Plan::Transcode { video, audio } => (video, audio),
        _ => (false, false),
    };
    if video_encode {
        match encoder {
            Encoder::Nvenc => push(&[
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-rc",
                "vbr",
                "-cq",
                "19",
                "-b:v",
                "0",
            ]),
            Encoder::X264 => push(&["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]),
        }
        // 8-bit 4:2:0 is what every H.264 decoder takes.
        push(&["-pix_fmt", "yuv420p"]);
    } else {
        push(&["-c:v", "copy"]);
        if probe
            .video
            .as_ref()
            .is_some_and(|video| video.codec == "hevc")
        {
            push(&["-tag:v", "hvc1"]);
        }
    }
    if probe.audio.is_some() {
        if audio_encode {
            // Opus keeps surround (5.1/7.1, mapping family 1) at about
            // 64 kbps per channel; stereo and mono become 192 kbps stereo.
            let channels = probe
                .audio
                .as_ref()
                .and_then(|audio| audio.channels)
                .unwrap_or(2)
                .clamp(1, 8);
            if channels <= 2 {
                push(&["-c:a", "libopus", "-b:a", "192k", "-ac", "2"]);
            } else {
                // Opus surround takes the standard layouts only: e.g. DTS's
                // "5.1(side)" is remapped to "5.1" (side → back surrounds).
                let layout = match channels {
                    3 => "3.0",
                    4 => "quad",
                    5 => "5.0",
                    6 => "5.1",
                    7 => "6.1",
                    _ => "7.1",
                };
                let filter = format!("aformat=channel_layouts={layout}");
                let bitrate = format!("{}k", 64 * channels);
                push(&[
                    "-af",
                    &filter,
                    "-c:a",
                    "libopus",
                    "-mapping_family",
                    "1",
                    "-b:a",
                    &bitrate,
                ]);
            }
        } else {
            push(&["-c:a", "copy"]);
        }
    }
    push(&[
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        "-progress",
        "pipe:1",
        "-nostats",
    ]);
    args.push(output.as_os_str().to_owned());
    args
}

/// A stable 16-hex-digit name for a prepared copy of `relative` as it is now
/// (FNV-1a over path, size, modification time and recipe version).
pub fn cache_name(relative: &str, size: u64, modified_ns: u128) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    let mut feed = |bytes: &[u8]| {
        for byte in bytes {
            hash ^= u64::from(*byte);
            hash = hash.wrapping_mul(0x0100_0000_01b3);
        }
    };
    feed(relative.as_bytes());
    feed(&[0]);
    feed(&size.to_le_bytes());
    feed(&modified_ns.to_le_bytes());
    feed(&RECIPE_VERSION.to_le_bytes());
    format!("{hash:016x}")
}

/// Whether `name` is a cache file name this module produces (`<16 hex>.mp4`).
pub fn is_cache_file_name(name: &str) -> bool {
    name.strip_suffix(".mp4").is_some_and(|stem| {
        stem.len() == 16
            && stem
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    })
}

/// Percent done from one `-progress` line (`out_time_us=…`).
pub fn parse_progress(line: &str, duration_seconds: Option<f64>) -> Option<f64> {
    let duration = duration_seconds?;
    let value = line.trim().strip_prefix("out_time_us=")?;
    let micros: f64 = value.parse().ok()?;
    (micros >= 0.0).then(|| (micros / 1_000_000.0 / duration * 100.0).clamp(0.0, 99.9))
}
