//! Local lyrics: a `.lrc` file next to a library song (`audio/Song.mp3` →
//! `audio/Song.lrc`). The song path is confined by `resolve_library_entry`, and
//! the sidecar must also resolve inside the library root. Online lookup happens
//! in the webview (CSP allows only `https://lrclib.net`); it matches on the
//! song's tags from [`read_track_info`] and stores what it finds with
//! [`save_local_lyrics`], so each song is looked up once.

use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;
use symphonia::core::formats::probe::Hint;
use symphonia::core::formats::{FormatOptions, TrackType};
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::{MetadataOptions, StandardTag};

use crate::paths::resolve_library_entry;

/// Lyrics files are small text; anything larger is not an LRC file.
pub const MAX_LRC_BYTES: u64 = 512 * 1024;

/// Returns the `.lrc` text for a library song, or `None` when there is none.
pub fn read_local_lyrics(root: &Path, relative_song: &str) -> Option<String> {
    if !relative_song.starts_with("audio/") {
        return None;
    }
    let song = resolve_library_entry(root, relative_song).ok()?;
    let candidate = song.with_extension("lrc");
    let resolved = candidate.canonicalize().ok()?;
    let root = root.canonicalize().ok()?;
    if !resolved.starts_with(&root) || !resolved.is_file() {
        return None;
    }
    if fs::metadata(&resolved).ok()?.len() > MAX_LRC_BYTES {
        return None;
    }
    let bytes = fs::read(&resolved).ok()?;
    let text = String::from_utf8_lossy(&bytes)
        .trim_start_matches('\u{feff}')
        .to_string();
    (!text.trim().is_empty()).then_some(text)
}

/// The `.lrc` path next to an audio library song, confined to the library.
fn lyrics_path(root: &Path, relative_song: &str) -> Option<PathBuf> {
    if !relative_song.starts_with("audio/") {
        return None;
    }
    let song = resolve_library_entry(root, relative_song).ok()?;
    Some(song.with_extension("lrc"))
}

/// Saves lyrics found online next to the song. Never replaces an existing
/// `.lrc` (the user's own file wins); returns whether a file was written.
pub fn save_local_lyrics(root: &Path, relative_song: &str, text: &str) -> bool {
    let text = text.trim();
    if text.is_empty() || text.len() as u64 > MAX_LRC_BYTES {
        return false;
    }
    let Some(path) = lyrics_path(root, relative_song) else {
        return false;
    };
    if path.exists() {
        return false;
    }
    let temporary = path.with_extension("lrc.part");
    let written = fs::write(
        &temporary,
        format!(
            "{text}
"
        ),
    )
    .is_ok()
        && fs::rename(&temporary, &path).is_ok();
    if !written {
        let _ = fs::remove_file(&temporary);
    }
    written
}

/// What the lyrics lookup matches on: the song's tags and real duration.
#[derive(Debug, Default, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TrackInfo {
    pub title: Option<String>,
    pub artist: Option<String>,
    pub album: Option<String>,
    pub duration_seconds: Option<f64>,
    /// Set when a lossless file (FLAC) was made from a lossy stream: the
    /// stream's codec and bitrate from Qtmedia's `SOURCE_CODEC` /
    /// `SOURCE_BITRATE` tags ("Opus 160 kbps"), or "unknown" for a FLAC that
    /// FFmpeg wrote (`ENCODER=Lavf…`, as every older Qtmedia download).
    pub lossy_source: Option<String>,
}

/// "opus" + "160" → "Opus 160 kbps".
fn describe_source(codec: &str, bitrate: Option<&str>) -> String {
    let name = match codec.to_ascii_lowercase().as_str() {
        "opus" => "Opus".to_owned(),
        "aac" => "AAC".to_owned(),
        "vorbis" => "Vorbis".to_owned(),
        "mp3" => "MP3".to_owned(),
        other => other.to_ascii_uppercase(),
    };
    match bitrate.map(str::trim).filter(|value| !value.is_empty()) {
        Some(kbps) => format!("{name} {kbps} kbps"),
        None => name,
    }
}

/// Reads title/artist/album tags (Vorbis comments or ID3) and the duration of
/// an audio library song. Missing tags are `None`; unreadable files yield an
/// empty `TrackInfo`.
pub fn read_track_info(root: &Path, relative_song: &str) -> Option<TrackInfo> {
    if !relative_song.starts_with("audio/") {
        return None;
    }
    let song = resolve_library_entry(root, relative_song).ok()?;
    let mut info = TrackInfo::default();
    let Ok(file) = fs::File::open(&song) else {
        return Some(info);
    };
    let stream = MediaSourceStream::new(Box::new(file), Default::default());
    let mut hint = Hint::new();
    if let Some(extension) = song.extension().and_then(|value| value.to_str()) {
        hint.with_extension(extension);
    }
    let Ok(mut reader) = symphonia::default::get_probe().probe(
        &hint,
        stream,
        FormatOptions::default(),
        MetadataOptions::default(),
    ) else {
        return Some(info);
    };
    let mut decoded_shape = (None, None);
    if let Some(track) = reader.default_track(TrackType::Audio) {
        let rate = track
            .codec_params
            .as_ref()
            .and_then(|params| params.audio())
            .and_then(|params| params.sample_rate);
        let bits = track
            .codec_params
            .as_ref()
            .and_then(|params| params.audio())
            .and_then(|params| params.bits_per_sample);
        decoded_shape = (rate, bits);
        if let (Some(frames), Some(rate)) = (track.num_frames, rate) {
            info.duration_seconds = Some(frames as f64 / f64::from(rate));
        }
    }
    let mut metadata = reader.metadata();
    let mut revisions = Vec::new();
    while let Some(revision) = metadata.pop() {
        revisions.push(revision);
    }
    revisions.extend(metadata.current().cloned());
    let raw = |wanted: &str| {
        revisions
            .iter()
            .flat_map(|revision| revision.media.tags.iter())
            .find_map(|tag| match &tag.raw.value {
                symphonia::core::meta::RawValue::String(value)
                    if tag.raw.key.eq_ignore_ascii_case(wanted) && !value.trim().is_empty() =>
                {
                    Some(value.trim().to_owned())
                }
                _ => None,
            })
    };
    let is_flac = song
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("flac"));
    if is_flac {
        info.lossy_source = match raw("SOURCE_CODEC") {
            Some(codec) => Some(describe_source(&codec, raw("SOURCE_BITRATE").as_deref())),
            // FFmpeg writes decoded Opus/AAC as 24-bit at 44.1/48 kHz (every
            // older Qtmedia download); CD rips are 16-bit, hi-res masters
            // 88.2 kHz and up, so those are taken as lossless.
            None => raw("ENCODER")
                .filter(|encoder| encoder.starts_with("Lavf"))
                .filter(|_| matches!(decoded_shape, (Some(44_100 | 48_000), Some(24))))
                .map(|_| "unknown".to_owned()),
        };
    }
    for revision in &revisions {
        for tag in &revision.media.tags {
            let (slot, value) = match &tag.std {
                Some(StandardTag::TrackTitle(value)) => (&mut info.title, value),
                Some(StandardTag::Artist(value)) => (&mut info.artist, value),
                Some(StandardTag::Album(value)) => (&mut info.album, value),
                _ => continue,
            };
            let value = value.trim();
            if slot.is_none() && !value.is_empty() {
                *slot = Some(value.to_owned());
            }
        }
    }
    Some(info)
}
