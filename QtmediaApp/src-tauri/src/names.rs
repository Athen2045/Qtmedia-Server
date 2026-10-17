//! Clean file names for media already in a library.
//!
//! Older engines saved `Title [media-<id>].ext`. This renames every such item
//! to `Title.ext` (or `Title (2).ext` when that stem is in use) as one group:
//! the media, its `.lrc` lyrics and its cover share a stem, which is how the
//! library scan pairs them. A prepared playback copy is renamed to its new
//! cache name so the video is not prepared again.
//!
//! Every rename goes into a log under the library root as library-relative
//! `{from, to}` pairs. The webview reads it (`library_renames`) to update the
//! playlists and resume positions it keeps by relative path.

use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use serde::{Deserialize, Serialize};

use crate::paths::{AUDIO_EXTENSIONS, VIDEO_EXTENSIONS};
use crate::playback::cache_name;

/// The library folders whose files share stems.
const STEM_FOLDERS: [&str; 3] = ["audio", "video", "artwork"];
const TAG_START: &str = " [media-";
const MAX_STEM_CHARS: usize = 120;
/// Windows refuses these as file names, with or without an extension.
const RESERVED_STEMS: [&str; 22] = [
    "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8",
    "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Rename {
    pub from: String,
    pub to: String,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct RenameLog {
    version: u32,
    /// Library root (as the app stores it) → renames in the order they happened.
    libraries: BTreeMap<String, Vec<Rename>>,
}

/// `stem` without its ` [media-<id>]` tag, or `None` when it has none.
pub fn untagged_stem(stem: &str) -> Option<String> {
    let start = stem.find(TAG_START)?;
    let rest = &stem[start + TAG_START.len()..];
    let end = rest.find(']')?;
    let id = &rest[..end];
    if id.is_empty()
        || !id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        return None;
    }
    Some(format!("{}{}", &stem[..start], &rest[end + 1..]))
}

/// A stem that is safe on every OS: trimmed, at most 120 characters, never a
/// Windows device name, never empty.
pub fn safe_stem(stem: &str) -> String {
    let trim = |value: &str| {
        value
            .trim_matches(|c| c == ' ' || c == '.' || c == '_')
            .to_owned()
    };
    let trimmed = trim(stem);
    let shortened: String = trimmed.chars().take(MAX_STEM_CHARS).collect();
    let cleaned = trim(&shortened);
    if cleaned.is_empty() {
        "media".to_owned()
    } else if RESERVED_STEMS.contains(&cleaned.to_lowercase().as_str()) {
        format!("{cleaned}_")
    } else {
        cleaned
    }
}

fn stem_of(path: &Path) -> Option<&str> {
    path.file_stem().and_then(|value| value.to_str())
}

fn is_media(folder: &str, path: &Path) -> bool {
    let extensions = match folder {
        "audio" => AUDIO_EXTENSIONS,
        "video" => VIDEO_EXTENSIONS,
        _ => return false,
    };
    path.extension()
        .and_then(|value| value.to_str())
        .is_some_and(|extension| extensions.contains(&extension.to_ascii_lowercase().as_str()))
}

fn free_stem(base: &str, taken: &HashSet<String>) -> Option<String> {
    if !taken.contains(&base.to_lowercase()) {
        return Some(base.to_owned());
    }
    (2..10_000)
        .map(|index| format!("{base} ({index})"))
        .find(|candidate| !taken.contains(&candidate.to_lowercase()))
}

fn modified_ns(path: &Path) -> Option<(u64, u128)> {
    let metadata = fs::metadata(path).ok()?;
    let modified = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
        .map_or(0, |duration| duration.as_nanos());
    Some((metadata.len(), modified))
}

/// Renames the prepared copy of a video so its cache name follows the file.
fn carry_playback_copy(cache_dir: &Path, from: &str, to: &str, path: &Path) {
    let Some((size, modified)) = modified_ns(path) else {
        return;
    };
    let old = cache_dir.join(format!("{}.mp4", cache_name(from, size, modified)));
    let new = cache_dir.join(format!("{}.mp4", cache_name(to, size, modified)));
    if old.is_file() && !new.exists() {
        let _ = fs::rename(old, new);
    }
}

fn read_log(log_path: &Path) -> RenameLog {
    fs::read(log_path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

fn write_log(log_path: &Path, log: &RenameLog) -> std::io::Result<()> {
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temporary = log_path.with_extension("json.tmp");
    fs::write(&temporary, serde_json::to_vec_pretty(log)?)?;
    fs::rename(&temporary, log_path)
}

fn root_key(root: &Path) -> String {
    root.to_string_lossy().into_owned()
}

/// The renames recorded for `root`, oldest first.
pub fn logged_renames(log_path: &Path, root: &Path) -> Vec<Rename> {
    read_log(log_path)
        .libraries
        .remove(&root_key(root))
        .unwrap_or_default()
}

/// Renames every tagged item in `root` and records it. Returns this run's
/// renames. Items that cannot be renamed completely are left as they were.
pub fn tidy_library(root: &Path, cache_dir: Option<&Path>, log_path: &Path) -> Vec<Rename> {
    let mut taken = HashSet::new();
    // Old stem → files (folder, path) that carry it.
    let mut groups: BTreeMap<String, Vec<(&str, PathBuf)>> = BTreeMap::new();
    for folder in STEM_FOLDERS {
        let Ok(entries) = fs::read_dir(root.join(folder)) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let Some(stem) = stem_of(&path) else { continue };
            taken.insert(stem.to_lowercase());
            let is_file = entry.file_type().is_ok_and(|kind| kind.is_file());
            if is_file && untagged_stem(stem).is_some() {
                groups
                    .entry(stem.to_owned())
                    .or_default()
                    .push((folder, path.clone()));
            }
        }
    }
    // Lyrics or covers left behind by deleted media stay as they are; they
    // must not take a clean name ahead of a real song or video.
    groups.retain(|_, files| files.iter().any(|(folder, path)| is_media(folder, path)));
    if groups.is_empty() {
        return Vec::new();
    }

    let mut log = read_log(log_path);
    log.version = 1;
    let mut done = Vec::new();
    for (old_stem, files) in groups {
        let Some(base) = untagged_stem(&old_stem).map(|stem| safe_stem(&stem)) else {
            continue;
        };
        let Some(new_stem) = free_stem(&base, &taken) else {
            continue;
        };
        let mut moved: Vec<(PathBuf, PathBuf, Rename)> = Vec::new();
        let mut failed = false;
        for (folder, from_path) in &files {
            let Some(name) = from_path.file_name().and_then(|value| value.to_str()) else {
                failed = true;
                break;
            };
            let suffix = &name[old_stem.len()..];
            let to_path = root.join(folder).join(format!("{new_stem}{suffix}"));
            // std's rename replaces an existing file on Windows; never do that.
            if to_path.exists() || fs::rename(from_path, &to_path).is_err() {
                failed = true;
                break;
            }
            let rename = Rename {
                from: format!("{folder}/{name}"),
                to: format!("{folder}/{new_stem}{suffix}"),
            };
            moved.push((from_path.clone(), to_path, rename));
        }
        if failed {
            // Put the group back so media, lyrics and cover keep one stem.
            for (from_path, to_path, _) in moved.into_iter().rev() {
                let _ = fs::rename(to_path, from_path);
            }
            continue;
        }
        taken.insert(new_stem.to_lowercase());
        let entry = log.libraries.entry(root_key(root)).or_default();
        for (_, to_path, rename) in moved {
            if let (Some(cache_dir), true) = (cache_dir, rename.from.starts_with("video/")) {
                carry_playback_copy(cache_dir, &rename.from, &rename.to, &to_path);
            }
            entry.push(rename.clone());
            done.push(rename);
        }
        let _ = write_log(log_path, &log);
    }
    done
}
