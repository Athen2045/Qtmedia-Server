//! Durations for the library listing.
//!
//! The engine's scan does not read media, so listings arrive without a
//! duration. Songs are measured with the audio decoder (FLAC STREAMINFO, MP3
//! Xing/Info headers); videos, and MP3s without a header, with the bundled
//! ffprobe. Results, including "unknown", are cached by library path, size and
//! modification time in `<app local data>/durations.json`, so a file is only
//! measured once.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

/// Measured at most this many files at once.
const WORKERS: usize = 4;

#[derive(Debug, Clone, PartialEq)]
pub struct Item {
    pub relative_path: String,
    pub size_bytes: u64,
    pub modified_at: f64,
}

#[derive(Default, Serialize, Deserialize)]
struct Stored {
    version: u32,
    /// `root|relative|size|modified` → seconds (`None` = could not be measured).
    entries: HashMap<String, Option<f64>>,
}

pub struct DurationCache {
    path: PathBuf,
    entries: Mutex<Option<HashMap<String, Option<f64>>>>,
}

fn key(root: &Path, item: &Item) -> String {
    format!(
        "{}|{}|{}|{}",
        root.to_string_lossy(),
        item.relative_path,
        item.size_bytes,
        item.modified_at
    )
}

impl DurationCache {
    pub fn new(path: PathBuf) -> Self {
        Self {
            path,
            entries: Mutex::new(None),
        }
    }

    fn load(&self) -> HashMap<String, Option<f64>> {
        fs::read(&self.path)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<Stored>(&bytes).ok())
            .map(|stored| stored.entries)
            .unwrap_or_default()
    }

    fn save(&self, entries: &HashMap<String, Option<f64>>) {
        let stored = Stored {
            version: 1,
            entries: entries.clone(),
        };
        let Ok(bytes) = serde_json::to_vec(&stored) else {
            return;
        };
        if let Some(parent) = self.path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let temporary = self.path.with_extension("json.tmp");
        if fs::write(&temporary, bytes).is_ok() {
            let _ = fs::rename(&temporary, &self.path);
        }
    }

    /// Durations for `items` in order, measuring (with `measure`) only files
    /// the cache has not seen. Entries of `root` that are no longer listed are
    /// dropped from the cache.
    pub fn durations(
        &self,
        root: &Path,
        items: &[Item],
        measure: impl Fn(&Item) -> Option<f64> + Sync,
    ) -> Vec<Option<f64>> {
        let mut guard = self
            .entries
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let entries = guard.get_or_insert_with(|| self.load());
        let keys: Vec<String> = items.iter().map(|item| key(root, item)).collect();
        let missing: Vec<usize> = (0..items.len())
            .filter(|&index| !entries.contains_key(&keys[index]))
            .collect();
        let measured: Vec<(usize, Option<f64>)> = std::thread::scope(|scope| {
            let chunk = missing.len().div_ceil(WORKERS).max(1);
            let handles: Vec<_> = missing
                .chunks(chunk)
                .map(|indexes| {
                    let measure = &measure;
                    scope.spawn(move || {
                        indexes
                            .iter()
                            .map(|&index| (index, measure(&items[index])))
                            .collect::<Vec<_>>()
                    })
                })
                .collect();
            handles
                .into_iter()
                .flat_map(|handle| handle.join().unwrap_or_default())
                .collect()
        });
        let prefix = format!("{}|", root.to_string_lossy());
        let listed: std::collections::HashSet<&String> = keys.iter().collect();
        let before = entries.len();
        entries.retain(|stored, _| !stored.starts_with(&prefix) || listed.contains(stored));
        let pruned = entries.len() != before;
        for (index, seconds) in &measured {
            entries.insert(keys[*index].clone(), *seconds);
        }
        if pruned || !measured.is_empty() {
            self.save(entries);
        }
        keys.iter()
            .map(|stored| entries.get(stored).copied().flatten())
            .collect()
    }
}

/// Seconds of a library file: the decoder for songs, ffprobe otherwise.
pub fn measure(root: &Path, relative: &str, ffprobe: Option<&Path>) -> Option<f64> {
    let decoded = if relative.starts_with("audio/") {
        crate::lyrics::read_track_info(root, relative).and_then(|info| info.duration_seconds)
    } else {
        None
    };
    decoded
        .or_else(|| {
            let path = crate::paths::resolve_library_entry(root, relative).ok()?;
            probe_duration(ffprobe?, &path)
        })
        .filter(|seconds| seconds.is_finite() && *seconds > 0.0)
}

fn probe_duration(ffprobe: &Path, path: &Path) -> Option<f64> {
    let mut command = Command::new(ffprobe);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let output = command
        .args([
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
        ])
        .arg(path)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    String::from_utf8_lossy(&output.stdout).trim().parse().ok()
}
