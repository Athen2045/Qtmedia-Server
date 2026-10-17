//! Removing library media for the Files "Delete" action.
//!
//! Every requested path goes through `resolve_library_entry`, so only audio and
//! video files inside the active library can be removed. Artwork, `temp/`,
//! folders and anything outside the root are refused. A removed file's cover
//! (`artwork/<stem>.<image>`, matched by stem like the library scan) goes too,
//! unless another audio or video file with that stem still uses it. The app
//! moves files to the system Recycle Bin/Trash; the remover is injected so
//! tests never touch it.

use std::collections::BTreeSet;
use std::path::Path;

use serde::Serialize;

use crate::paths::{
    resolve_artwork_entry, resolve_library_entry, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS,
};

/// Cover extensions, in the library scan's order (`sidecar/.../library.py`).
const ARTWORK_EXTENSIONS: [&str; 4] = ["jpg", "jpeg", "png", "webp"];

/// Upper bound for one request, so a single call cannot run unbounded.
pub const MAX_BATCH: usize = 2000;

#[derive(Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemovalReport {
    /// Relative paths that were removed (echoed back so the UI can update).
    pub removed: Vec<String>,
    /// How many requested paths were refused or could not be removed.
    pub failed: usize,
}

pub fn remove_entries(
    root: &Path,
    relative_paths: &[String],
    mut remove: impl FnMut(&Path) -> bool,
) -> RemovalReport {
    let mut report = RemovalReport::default();
    let unique: BTreeSet<&String> = relative_paths.iter().collect();
    for relative in unique {
        match resolve_library_entry(root, relative) {
            Ok(path) if remove(&path) => {
                report.removed.push(relative.clone());
                remove_unshared_artwork(root, &path, &mut remove);
                if relative.starts_with("video/") {
                    remove_unshared_subtitles(root, relative, &path, &mut remove);
                }
            }
            _ => report.failed += 1,
        }
    }
    report
}

/// Removes the covers of a just-removed media file when no other media file
/// with the same stem remains. A cover that cannot be removed is left in
/// place; the media removal still counts as done.
fn remove_unshared_artwork(root: &Path, removed: &Path, remove: &mut impl FnMut(&Path) -> bool) {
    let Some(stem) = removed.file_stem().and_then(|value| value.to_str()) else {
        return;
    };
    let media = AUDIO_EXTENSIONS
        .iter()
        .map(|extension| ("audio", extension))
        .chain(
            VIDEO_EXTENSIONS
                .iter()
                .map(|extension| ("video", extension)),
        );
    let shared = media.into_iter().any(|(folder, extension)| {
        resolve_library_entry(root, &format!("{folder}/{stem}.{extension}")).is_ok()
    });
    if shared {
        return;
    }
    for extension in ARTWORK_EXTENSIONS {
        if let Ok(cover) = resolve_artwork_entry(root, &format!("artwork/{stem}.{extension}")) {
            remove(&cover);
        }
    }
}

/// Removes the subtitle files of a just-removed video unless another video
/// with the same stem (e.g. `Film.mkv` beside `Film.mp4`) still uses them.
fn remove_unshared_subtitles(
    root: &Path,
    relative: &str,
    removed: &Path,
    remove: &mut impl FnMut(&Path) -> bool,
) {
    let Some(stem) = removed.file_stem().and_then(|value| value.to_str()) else {
        return;
    };
    let shared = VIDEO_EXTENSIONS
        .iter()
        .any(|extension| resolve_library_entry(root, &format!("video/{stem}.{extension}")).is_ok());
    if shared {
        return;
    }
    for subtitle in crate::subtitles::files_for(root, relative) {
        remove(&subtitle);
    }
}

/// Moves a file to the Recycle Bin (Windows) or Trash (macOS).
pub fn move_to_trash(path: &Path) -> bool {
    trash::delete(path).is_ok()
}
