//! Files → Import: copy music and videos the user picks into the library.
//! Songs (`paths::AUDIO_EXTENSIONS`) go to `audio/`, videos
//! (`paths::VIDEO_EXTENSIONS`) to `video/`; anything else is skipped. Each
//! file is copied to a `.part` name in the destination folder and renamed
//! when complete; an existing file is never overwritten ("Name (2).ext").

use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::paths::{AUDIO_EXTENSIONS, VIDEO_EXTENSIONS};

/// Upper bound for one pick, so a single call cannot run unbounded.
pub const MAX_IMPORT: usize = 500;

#[derive(Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportReport {
    /// Library-relative paths of the copies.
    pub imported: Vec<String>,
    /// Files not imported (unsupported type, unreadable, or past the limit).
    pub skipped: usize,
}

/// The library folder a file belongs in, by extension (`None` if unsupported).
pub fn folder_for(path: &Path) -> Option<&'static str> {
    let extension = path.extension()?.to_str()?.to_ascii_lowercase();
    if AUDIO_EXTENSIONS.contains(&extension.as_str()) {
        Some("audio")
    } else if VIDEO_EXTENSIONS.contains(&extension.as_str()) {
        Some("video")
    } else {
        None
    }
}

/// `dir/name`, or `dir/stem (2).ext`, `(3)`… when the name is taken.
pub fn free_name(dir: &Path, file_name: &str) -> PathBuf {
    let candidate = dir.join(file_name);
    if !candidate.exists() {
        return candidate;
    }
    let path = Path::new(file_name);
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("Imported");
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    (2..)
        .map(|number| dir.join(format!("{stem} ({number}).{extension}")))
        .find(|candidate| !candidate.exists())
        .expect("an unused name exists")
}

/// Copies `sources` into the library at `root` with `copy(from, to)`.
pub fn import_files(
    root: &Path,
    sources: &[PathBuf],
    mut copy: impl FnMut(&Path, &Path) -> bool,
) -> ImportReport {
    let mut report = ImportReport::default();
    for (index, source) in sources.iter().enumerate() {
        let file_name = source.file_name().and_then(|value| value.to_str());
        let folder = folder_for(source);
        let (Some(file_name), Some(folder), true) = (file_name, folder, index < MAX_IMPORT) else {
            report.skipped += 1;
            continue;
        };
        if !source.is_file() {
            report.skipped += 1;
            continue;
        }
        let dir = root.join(folder);
        if fs::create_dir_all(&dir).is_err() {
            report.skipped += 1;
            continue;
        }
        let target = free_name(&dir, file_name);
        let part = target.with_file_name(format!(
            "{}.part",
            target
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("import")
        ));
        if copy(source, &part) && fs::rename(&part, &target).is_ok() {
            let name = target
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or_default();
            report.imported.push(format!("{folder}/{name}"));
        } else {
            let _ = fs::remove_file(&part);
            report.skipped += 1;
        }
    }
    report
}

/// The real copy (keeps the source untouched).
pub fn copy_file(from: &Path, to: &Path) -> bool {
    fs::copy(from, to).is_ok()
}
