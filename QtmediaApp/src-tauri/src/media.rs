//! `qtmedia://` media transport for the in-app music and video players.
//!
//! Serves only library songs (`audio/*.mp3|flac`) and videos (`video/*`, see
//! `paths::VIDEO_EXTENSIONS`) from the active library,
//! resolved through the same confinement as `open_media`. Supports byte ranges
//! so `<audio>`/`<video>` can seek. Bodies are built in memory, so every
//! response is bounded (library videos exceed 1 GB). The webview never learns
//! absolute paths and gets no filesystem scope.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

use crate::paths::resolve_library_entry;

pub const SCHEME: &str = "qtmedia";

/// Largest body returned for any single request.
const MAX_CHUNK: u64 = 2 * 1024 * 1024;

#[derive(Debug, PartialEq, Eq)]
pub struct MediaResponse {
    pub status: u16,
    pub headers: Vec<(&'static str, String)>,
    pub body: Vec<u8>,
}

impl MediaResponse {
    fn empty(status: u16) -> Self {
        Self {
            status,
            headers: Vec::new(),
            body: Vec::new(),
        }
    }
}

/// Parses a single `bytes=start-end` / `bytes=start-` / `bytes=-suffix` range
/// against a file of `len` bytes. Returns the inclusive byte span.
pub fn parse_range(header: &str, len: u64) -> Option<(u64, u64)> {
    if len == 0 {
        return None;
    }
    let spec = header.trim().strip_prefix("bytes=")?;
    if spec.contains(',') {
        return None;
    }
    let (start, end) = spec.split_once('-')?;
    let (start, end) = match (start.trim(), end.trim()) {
        ("", suffix) => {
            let suffix: u64 = suffix.parse().ok()?;
            if suffix == 0 {
                return None;
            }
            (len.saturating_sub(suffix), len - 1)
        }
        (start, "") => {
            let start: u64 = start.parse().ok()?;
            (start, (start + MAX_CHUNK - 1).min(len - 1))
        }
        (start, end) => {
            let start: u64 = start.parse().ok()?;
            let end: u64 = end.parse().ok()?;
            (start, end.min(len - 1))
        }
    };
    (start <= end && start < len).then_some((start, end))
}

/// Decodes `%XX` escapes from a URI path; rejects malformed or non-UTF-8 input.
pub fn percent_decode(value: &str) -> Option<String> {
    let bytes = value.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            let hex = value.get(index + 1..index + 3)?;
            out.push(u8::from_str_radix(hex, 16).ok()?);
            index += 3;
        } else {
            out.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(out).ok()
}

fn video_content_type(relative: &str) -> &'static str {
    let lower = relative.to_ascii_lowercase();
    match lower.rsplit('.').next().unwrap_or_default() {
        "webm" => "video/webm",
        "mkv" => "video/x-matroska",
        "mov" => "video/quicktime",
        "avi" => "video/x-msvideo",
        _ => "video/mp4",
    }
}

/// The CORS origin to allow for a media request, if it comes from the app's
/// own webview. The video player routes audio through Web Audio (stable
/// volume), which needs CORS-clean media; other origins get nothing.
pub fn allowed_origin(origin: Option<&str>) -> Option<&str> {
    let origin = origin?;
    let app = matches!(
        origin,
        "http://tauri.localhost" | "https://tauri.localhost" | "tauri://localhost"
    );
    // `pnpm desktop:dev` serves the frontend from Vite on localhost:1420.
    let dev = origin == "http://localhost:1420";
    (app || dev).then_some(origin)
}

/// Builds the response for `uri_path` (the request URI path, still encoded).
pub fn serve(root: &Path, method: &str, uri_path: &str, range: Option<&str>) -> MediaResponse {
    serve_with_limit(root, method, uri_path, range, MAX_CHUNK)
}

/// `serve` with an explicit body limit (exposed for tests).
pub fn serve_with_limit(
    root: &Path,
    method: &str,
    uri_path: &str,
    range: Option<&str>,
    limit: u64,
) -> MediaResponse {
    let limit = limit.max(1);
    if method != "GET" && method != "HEAD" {
        return MediaResponse::empty(405);
    }
    let Some(relative) = percent_decode(uri_path.trim_start_matches('/')) else {
        return MediaResponse::empty(400);
    };
    // Normalise the separator the frontend may encode, then confine to the
    // media folders; `resolve_library_entry` also enforces the extension.
    let relative = relative.replace('\\', "/");
    let content_type = if relative.starts_with("audio/") {
        if relative.to_ascii_lowercase().ends_with(".flac") {
            "audio/flac"
        } else {
            "audio/mpeg"
        }
    } else if relative.starts_with("video/") {
        video_content_type(&relative)
    } else {
        return MediaResponse::empty(403);
    };
    let Ok(path) = resolve_library_entry(root, &relative) else {
        return MediaResponse::empty(404);
    };
    serve_path(&path, content_type, method, range, limit)
}

/// The prepared-copy name in a `qtmedia://localhost/playback/<16 hex>.mp4`
/// request, if that is what `uri_path` asks for.
pub fn playback_name(uri_path: &str) -> Option<String> {
    let relative = percent_decode(uri_path.trim_start_matches('/'))?.replace('\\', "/");
    let name = relative.strip_prefix("playback/")?;
    crate::playback::is_cache_file_name(name).then(|| name.to_owned())
}

/// Serves a prepared copy from the playback cache (see `preparer.rs`). Only
/// strict `<16 hex>.mp4` names directly inside `cache_dir` are served.
pub fn serve_playback(
    cache_dir: &Path,
    method: &str,
    uri_path: &str,
    range: Option<&str>,
) -> MediaResponse {
    if method != "GET" && method != "HEAD" {
        return MediaResponse::empty(405);
    }
    let Some(name) = playback_name(uri_path) else {
        return MediaResponse::empty(404);
    };
    serve_path(&cache_dir.join(name), "video/mp4", method, range, MAX_CHUNK)
}

/// The cache name in a `qtmedia://localhost/subtitles/<16 hex>.vtt` request.
pub fn subtitle_name(uri_path: &str) -> Option<String> {
    let relative = percent_decode(uri_path.trim_start_matches('/'))?.replace('\\', "/");
    let name = relative.strip_prefix("subtitles/")?;
    crate::subtitles::is_cache_file_name(name).then(|| name.to_owned())
}

/// Serves a converted subtitle track; only strict names inside `cache_dir`.
pub fn serve_subtitle(cache_dir: &Path, method: &str, uri_path: &str) -> MediaResponse {
    if method != "GET" && method != "HEAD" {
        return MediaResponse::empty(405);
    }
    let Some(name) = subtitle_name(uri_path) else {
        return MediaResponse::empty(404);
    };
    serve_path(
        &cache_dir.join(name),
        "text/vtt; charset=utf-8",
        method,
        None,
        crate::subtitles::MAX_SUBTITLE_BYTES * 2,
    )
}

fn serve_path(
    path: &Path,
    content_type: &str,
    method: &str,
    range: Option<&str>,
    limit: u64,
) -> MediaResponse {
    let limit = limit.max(1);
    let Ok(mut file) = File::open(path) else {
        return MediaResponse::empty(404);
    };
    let Ok(len) = file.metadata().map(|metadata| metadata.len()) else {
        return MediaResponse::empty(404);
    };

    let mut headers = vec![
        ("Content-Type", content_type.to_string()),
        ("Accept-Ranges", "bytes".to_string()),
        ("Cache-Control", "no-store".to_string()),
    ];
    let (status, start, end) = match range {
        Some(value) => match parse_range(value, len) {
            Some((start, end)) => {
                let end = end.min(start + limit - 1);
                headers.push(("Content-Range", format!("bytes {start}-{end}/{len}")));
                (206, start, end)
            }
            None => {
                return MediaResponse {
                    status: 416,
                    headers: vec![("Content-Range", format!("bytes */{len}"))],
                    body: Vec::new(),
                }
            }
        },
        None if len == 0 => (200, 0, 0),
        None if len > limit => {
            headers.push(("Content-Range", format!("bytes 0-{}/{len}", limit - 1)));
            (206, 0, limit - 1)
        }
        None => (200, 0, len - 1),
    };
    let count = if len == 0 { 0 } else { end - start + 1 };
    headers.push(("Content-Length", count.to_string()));
    if method == "HEAD" || count == 0 {
        return MediaResponse {
            status,
            headers,
            body: Vec::new(),
        };
    }
    let mut body = vec![0; count as usize];
    if file.seek(SeekFrom::Start(start)).is_err() || file.read_exact(&mut body).is_err() {
        return MediaResponse::empty(500);
    }
    MediaResponse {
        status,
        headers,
        body,
    }
}
