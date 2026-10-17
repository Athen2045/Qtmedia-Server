//! Subtitles for library videos (see
//! `docs/superpowers/specs/2026-10-17-video-subtitles-design.md`).
//!
//! Tracks come from `.srt`/`.vtt` files next to a video and from text
//! subtitle streams inside it. Each is converted to WebVTT and written to the
//! subtitle cache as `<16 hex>.vtt`, which `media.rs` serves as
//! `qtmedia://localhost/subtitles/<name>.vtt`.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::UNIX_EPOCH;

use serde::{Deserialize, Serialize};

use crate::paths::resolve_library_entry;

/// Where converted tracks live (`<app local data>/subtitle-cache`).
pub struct SubtitleCache(pub PathBuf);

/// Subtitle files larger than this are not read.
pub const MAX_SUBTITLE_BYTES: u64 = 4 * 1024 * 1024;
pub const SUBTITLE_EXTENSIONS: [&str; 2] = ["srt", "vtt"];
/// Embedded codecs ffmpeg can turn into WebVTT text.
const TEXT_CODECS: [&str; 7] = ["subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"];

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SubtitleTrack {
    /// Stable within a video: `file:<name>` or `stream:<index>`.
    pub id: String,
    pub label: Option<String>,
    /// As written in the file name or stream tag (`en`, `eng`, `pt-BR`).
    pub language: Option<String>,
    /// `qtmedia://` path of the WebVTT copy (`subtitles/<16 hex>.vtt`).
    pub url: String,
}

#[derive(Debug, Default, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Subtitles {
    pub tracks: Vec<SubtitleTrack>,
    /// Picture-based streams (PGS, DVD) that cannot be shown as text.
    pub unsupported: usize,
}

/// Whether `name` is a cache file name this module writes.
pub fn is_cache_file_name(name: &str) -> bool {
    name.strip_suffix(".vtt").is_some_and(|stem| {
        stem.len() == 16
            && stem
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}

fn hash_name(parts: &[&[u8]]) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for part in parts {
        for byte in part.iter().chain(std::iter::once(&0u8)) {
            hash ^= u64::from(*byte);
            hash = hash.wrapping_mul(0x0100_0000_01b3);
        }
    }
    format!("{hash:016x}")
}

fn identity(path: &Path) -> Option<(u64, u128)> {
    let metadata = fs::metadata(path).ok()?;
    let modified = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
        .map_or(0, |duration| duration.as_nanos());
    Some((metadata.len(), modified))
}

/// The cache name for one track of one source file as it is now.
fn cache_name(relative: &str, track: &str, path: &Path) -> Option<String> {
    let (size, modified) = identity(path)?;
    Some(hash_name(&[
        relative.as_bytes(),
        track.as_bytes(),
        &size.to_le_bytes(),
        &modified.to_le_bytes(),
    ]))
}

/// Text of a subtitle file: UTF-8 (BOM optional) or UTF-16 with a BOM.
pub fn decode_text(bytes: &[u8]) -> String {
    match bytes {
        [0xEF, 0xBB, 0xBF, rest @ ..] => String::from_utf8_lossy(rest).into_owned(),
        [0xFF, 0xFE, rest @ ..] => utf16(rest, u16::from_le_bytes),
        [0xFE, 0xFF, rest @ ..] => utf16(rest, u16::from_be_bytes),
        _ => String::from_utf8_lossy(bytes).into_owned(),
    }
}

fn utf16(bytes: &[u8], read: fn([u8; 2]) -> u16) -> String {
    let units: Vec<u16> = bytes
        .chunks_exact(2)
        .map(|pair| read([pair[0], pair[1]]))
        .collect();
    String::from_utf16_lossy(&units)
}

/// Removes `<font …>` / `</font>` tags (common in SRT, not part of WebVTT).
fn strip_font_tags(line: &str) -> String {
    let mut out = String::with_capacity(line.len());
    let mut rest = line;
    while let Some(start) = rest.find('<') {
        out.push_str(&rest[..start]);
        let tag = &rest[start..];
        let lower = tag.get(..6).unwrap_or(tag).to_ascii_lowercase();
        if lower.starts_with("<font") || lower.starts_with("</font") {
            match tag.find('>') {
                Some(end) => rest = &tag[end + 1..],
                None => {
                    rest = "";
                }
            }
        } else {
            out.push('<');
            rest = &tag[1..];
        }
    }
    out.push_str(rest);
    out
}

/// SubRip → WebVTT: header, `,` → `.` in timings, `<font>` tags removed.
pub fn srt_to_vtt(text: &str) -> String {
    let mut out = String::from("WEBVTT\n\n");
    for line in text.replace("\r\n", "\n").replace('\r', "\n").lines() {
        if line.contains("-->") {
            out.push_str(&line.replace(',', "."));
        } else {
            out.push_str(&strip_font_tags(line));
        }
        out.push('\n');
    }
    out
}

/// A WebVTT file as the player needs it: always starting with `WEBVTT`.
pub fn normalize_vtt(text: &str) -> String {
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    if text.trim_start().starts_with("WEBVTT") {
        text
    } else {
        format!("WEBVTT\n\n{text}")
    }
}

/// `(label, language)` from the part of a file name between the video stem
/// and the extension: `en` → language, `English` → label, `en.forced` → both.
pub fn describe_middle(middle: &str) -> (Option<String>, Option<String>) {
    let middle = middle.trim_matches('.');
    if middle.is_empty() {
        return (None, None);
    }
    let first = middle.split('.').next().unwrap_or_default();
    let is_language = {
        let (base, region) = first.split_once('-').unwrap_or((first, ""));
        (2..=3).contains(&base.len())
            && base.bytes().all(|byte| byte.is_ascii_alphabetic())
            && (region.is_empty() || (2..=4).contains(&region.len()))
    };
    if is_language {
        let rest = middle[first.len()..].trim_matches('.');
        (
            (!rest.is_empty()).then(|| rest.to_owned()),
            Some(first.to_owned()),
        )
    } else {
        (Some(middle.to_owned()), None)
    }
}

/// Subtitle files next to `video` (library-relative `video/<stem>.<ext>`):
/// `(file name, middle part)`, sorted by name.
fn sidecar_files(root: &Path, relative_video: &str) -> Vec<(String, String)> {
    let Some(name) = relative_video.strip_prefix("video/") else {
        return Vec::new();
    };
    let Some(stem) = Path::new(name).file_stem().and_then(|value| value.to_str()) else {
        return Vec::new();
    };
    let Ok(entries) = fs::read_dir(root.join("video")) else {
        return Vec::new();
    };
    let mut found: Vec<(String, String)> = entries
        .flatten()
        .filter(|entry| entry.file_type().is_ok_and(|kind| kind.is_file()))
        .filter_map(|entry| entry.file_name().to_str().map(str::to_owned))
        .filter_map(|file| {
            let (base, extension) = file.rsplit_once('.')?;
            if !SUBTITLE_EXTENSIONS.contains(&extension.to_ascii_lowercase().as_str()) {
                return None;
            }
            let middle = if base == stem {
                String::new()
            } else {
                base.strip_prefix(stem)?.strip_prefix('.')?.to_owned()
            };
            Some((file, middle))
        })
        .collect();
    found.sort();
    found
}

#[derive(Deserialize)]
struct ProbeOutput {
    #[serde(default)]
    streams: Vec<ProbeStream>,
}

#[derive(Deserialize)]
struct ProbeStream {
    index: u32,
    #[serde(default)]
    codec_name: Option<String>,
    #[serde(default)]
    tags: std::collections::HashMap<String, String>,
}

/// An embedded subtitle stream from ffprobe's JSON.
#[derive(Debug, Clone, PartialEq)]
pub struct EmbeddedStream {
    pub index: u32,
    pub text: bool,
    pub language: Option<String>,
    pub title: Option<String>,
}

/// Whether a stream title is an advert or site name rather than a track
/// name: a web address, or (with `shared`) the same title on every stream.
fn is_junk_title(title: &str) -> bool {
    let lower = title.to_ascii_lowercase();
    lower.contains("://")
        || lower.contains("www.")
        || lower
            .split(|c: char| !c.is_ascii_alphanumeric() && c != '.')
            .any(|word| {
                word.rsplit_once('.').is_some_and(|(name, tld)| {
                    !name.is_empty()
                        && [
                            "com", "net", "org", "cc", "io", "to", "me", "tv", "xyz", "info", "ru",
                        ]
                        .contains(&tld)
                })
            })
}

pub fn parse_streams(json: &str) -> Vec<EmbeddedStream> {
    let mut streams = parse_streams_raw(json);
    // A title on every stream is a release tag, not a track name.
    let shared = streams.len() > 1
        && streams
            .iter()
            .all(|stream| stream.title.is_some() && stream.title == streams[0].title);
    for stream in &mut streams {
        if shared || stream.title.as_deref().is_some_and(is_junk_title) {
            stream.title = None;
        }
    }
    streams
}

fn parse_streams_raw(json: &str) -> Vec<EmbeddedStream> {
    let Ok(output) = serde_json::from_str::<ProbeOutput>(json) else {
        return Vec::new();
    };
    output
        .streams
        .into_iter()
        .map(|stream| {
            let tag = |key: &str| {
                stream
                    .tags
                    .iter()
                    .find(|(name, _)| name.eq_ignore_ascii_case(key))
                    .map(|(_, value)| value.trim().to_owned())
                    .filter(|value| !value.is_empty() && value != "und")
            };
            EmbeddedStream {
                index: stream.index,
                text: stream
                    .codec_name
                    .as_deref()
                    .is_some_and(|codec| TEXT_CODECS.contains(&codec)),
                language: tag("language"),
                title: tag("title"),
            }
        })
        .collect()
}

fn command(program: &Path) -> Command {
    #[allow(unused_mut)]
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

fn probe_streams(ffprobe: &Path, video: &Path) -> Vec<EmbeddedStream> {
    let Ok(output) = command(ffprobe)
        .args([
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index,codec_name:stream_tags=language,title",
            "-of",
            "json",
        ])
        .arg(video)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
    else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }
    parse_streams(&String::from_utf8_lossy(&output.stdout))
}

/// Extracts `streams` (index, destination) to WebVTT in one pass over `video`.
fn extract_streams(ffmpeg: &Path, video: &Path, streams: &[(u32, PathBuf)]) {
    if streams.is_empty() {
        return;
    }
    let mut run = command(ffmpeg);
    run.args(["-nostdin", "-v", "error", "-y", "-i"]).arg(video);
    let mut parts: Vec<(PathBuf, PathBuf)> = Vec::new();
    for (index, destination) in streams {
        let part = destination.with_extension("vtt.part");
        run.args([
            "-map",
            &format!("0:{index}"),
            "-c:s",
            "webvtt",
            "-f",
            "webvtt",
        ])
        .arg(&part);
        parts.push((part, destination.clone()));
    }
    let succeeded = run
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|status| status.success());
    for (part, destination) in parts {
        if succeeded && part.is_file() {
            let _ = fs::rename(&part, &destination);
        } else {
            let _ = fs::remove_file(&part);
        }
    }
}

/// Every subtitle track of `relative_video`, converted into `cache_dir`.
/// Tools that are missing only mean fewer tracks.
pub fn read_subtitles(
    root: &Path,
    relative_video: &str,
    cache_dir: &Path,
    ffprobe: Option<&Path>,
    ffmpeg: Option<&Path>,
) -> Result<Subtitles, &'static str> {
    if !relative_video.starts_with("video/") {
        return Err("unsafe_path");
    }
    let video = resolve_library_entry(root, relative_video).map_err(|error| match error {
        crate::paths::PathError::NotFound => "not_found",
        _ => "unsafe_path",
    })?;
    if !video.is_file() {
        return Err("not_found");
    }
    fs::create_dir_all(cache_dir).map_err(|_| "storage_unavailable")?;
    let mut result = Subtitles::default();

    for (file, middle) in sidecar_files(root, relative_video) {
        let path = root.join("video").join(&file);
        let relative = format!("video/{file}");
        let Some(name) = cache_name(&relative, "file", &path) else {
            continue;
        };
        let destination = cache_dir.join(format!("{name}.vtt"));
        if !destination.is_file() {
            let Ok(metadata) = fs::symlink_metadata(&path) else {
                continue;
            };
            if !metadata.is_file() || metadata.len() > MAX_SUBTITLE_BYTES {
                continue;
            }
            let Ok(bytes) = fs::read(&path) else { continue };
            let text = decode_text(&bytes);
            let vtt = if file.to_ascii_lowercase().ends_with(".srt") {
                srt_to_vtt(&text)
            } else {
                normalize_vtt(&text)
            };
            if fs::write(&destination, vtt).is_err() {
                continue;
            }
        }
        let (label, language) = describe_middle(&middle);
        result.tracks.push(SubtitleTrack {
            id: format!("file:{file}"),
            label,
            language,
            url: format!("subtitles/{name}.vtt"),
        });
    }

    if let Some(ffprobe) = ffprobe {
        let streams = probe_streams(ffprobe, &video);
        result.unsupported = streams.iter().filter(|stream| !stream.text).count();
        let text: Vec<(EmbeddedStream, String)> = streams
            .into_iter()
            .filter(|stream| stream.text)
            .filter_map(|stream| {
                let name = cache_name(relative_video, &format!("stream:{}", stream.index), &video)?;
                Some((stream, name))
            })
            .collect();
        if let Some(ffmpeg) = ffmpeg {
            let missing: Vec<(u32, PathBuf)> = text
                .iter()
                .filter(|(_, name)| !cache_dir.join(format!("{name}.vtt")).is_file())
                .map(|(stream, name)| (stream.index, cache_dir.join(format!("{name}.vtt"))))
                .collect();
            extract_streams(ffmpeg, &video, &missing);
        }
        for (stream, name) in text {
            if !cache_dir.join(format!("{name}.vtt")).is_file() {
                continue;
            }
            result.tracks.push(SubtitleTrack {
                id: format!("stream:{}", stream.index),
                label: stream.title,
                language: stream.language,
                url: format!("subtitles/{name}.vtt"),
            });
        }
    }
    Ok(result)
}

/// Subtitle files that belong to `relative_video` (removed along with it).
pub fn files_for(root: &Path, relative_video: &str) -> Vec<PathBuf> {
    sidecar_files(root, relative_video)
        .into_iter()
        .map(|(file, _)| root.join("video").join(file))
        .collect()
}

/// Copies picked `.srt`/`.vtt` files next to `relative_video` as
/// `<stem>.<picked name>.<ext>` (numbered when taken). Returns how many.
pub fn add_files(
    root: &Path,
    relative_video: &str,
    picked: &[PathBuf],
) -> Result<usize, &'static str> {
    let video = resolve_library_entry(root, relative_video).map_err(|_| "unsafe_path")?;
    if !relative_video.starts_with("video/") {
        return Err("unsafe_path");
    }
    let stem = video
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or("unsafe_path")?
        .to_owned();
    let mut added = 0;
    for source in picked {
        let Some(extension) = source
            .extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            .filter(|extension| SUBTITLE_EXTENSIONS.contains(&extension.as_str()))
        else {
            continue;
        };
        let Ok(metadata) = fs::metadata(source) else {
            continue;
        };
        if !metadata.is_file() || metadata.len() > MAX_SUBTITLE_BYTES {
            continue;
        }
        let picked_name = source
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or("Subtitles");
        // Keep the label readable and the name inside `video/`.
        let label: String = picked_name
            .chars()
            .map(|c| {
                if "\\/:*?\"<>|".contains(c) || c.is_control() {
                    '_'
                } else {
                    c
                }
            })
            .collect::<String>()
            .trim_matches(|c| c == ' ' || c == '.')
            .chars()
            .take(60)
            .collect();
        let label = if label.is_empty() || label.eq_ignore_ascii_case(&stem) {
            "Subtitles".to_owned()
        } else {
            label
        };
        let directory = root.join("video");
        let destination = std::iter::once(format!("{stem}.{label}.{extension}"))
            .chain((2..1000).map(|n| format!("{stem}.{label} {n}.{extension}")))
            .map(|name| directory.join(name))
            .find(|path| !path.exists());
        let Some(destination) = destination else {
            continue;
        };
        if fs::copy(source, &destination).is_ok() {
            added += 1;
        }
    }
    Ok(added)
}
