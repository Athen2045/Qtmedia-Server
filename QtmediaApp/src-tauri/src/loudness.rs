//! Loudness levelling: songs are measured once (EBU R128 integrated loudness
//! and true peak, with the bundled ffmpeg's `ebur128` filter) and played at
//! one level. The gain brings a song to [`TARGET_LUFS`]; boosts stop where
//! the true peak would pass [`PEAK_CEILING_DBTP`], so levelling never clips.
//! Measurements are cached by file (path, size, modification time) in
//! `<app local data>/loudness.json`; unmeasured songs play unchanged.

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::UNIX_EPOCH;

use serde::{Deserialize, Serialize};

/// YouTube's and Spotify's playback level (the library's songs come from
/// YouTube masters at about -6 to -11 LUFS, so most are turned down).
pub const TARGET_LUFS: f64 = -14.0;
/// Boosts stop here (−1 dBTP, the usual streaming ceiling).
pub const PEAK_CEILING_DBTP: f64 = -1.0;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Measure {
    /// Integrated loudness, LUFS.
    pub lufs: f64,
    /// True peak, dBTP.
    pub peak: f64,
}

/// Linear gain that plays `measure` at the target without passing the ceiling.
pub fn level_gain(measure: Measure) -> f32 {
    // -70 LUFS is ffmpeg's floor: silence, or too short to gate (< 0.4 s).
    if !measure.lufs.is_finite() || measure.lufs <= -70.0 {
        return 1.0;
    }
    let wanted = TARGET_LUFS - measure.lufs;
    let room = if measure.peak.is_finite() {
        PEAK_CEILING_DBTP - measure.peak
    } else {
        0.0
    };
    let db = if wanted > 0.0 {
        wanted.min(room.max(0.0))
    } else {
        wanted
    };
    10f64.powf(db / 20.0) as f32
}

/// Reads "I: -14.2 LUFS" and the true peak ("Peak: -0.3 dBFS" under "True
/// peak:") from ffmpeg's `ebur128` summary.
pub fn parse_summary(stderr: &str) -> Option<Measure> {
    let summary = &stderr[stderr.rfind("Summary:")?..];
    let number = |line: &str| -> Option<f64> {
        line.split_whitespace()
            .nth(1)
            .and_then(|value| value.parse().ok())
    };
    let lufs = summary
        .lines()
        .map(str::trim)
        .find(|line| line.starts_with("I:"))
        .and_then(number)?;
    let true_peak = summary.find("True peak:").map(|at| &summary[at..]);
    let peak = true_peak
        .and_then(|section| {
            section
                .lines()
                .map(str::trim)
                .find(|line| line.starts_with("Peak:"))
        })
        .and_then(number)
        .unwrap_or(f64::NAN);
    Some(Measure { lufs, peak })
}

/// Measures one song with ffmpeg; `None` when it cannot.
pub fn measure(ffmpeg: &Path, song: &Path) -> Option<Measure> {
    let mut command = Command::new(ffmpeg);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let output = command
        .args(["-nostdin", "-hide_banner", "-nostats", "-i"])
        .arg(song)
        .args([
            "-map",
            "0:a:0",
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    parse_summary(&String::from_utf8_lossy(&output.stderr))
}

fn file_key(path: &Path) -> Option<String> {
    let metadata = fs::metadata(path).ok()?;
    let modified = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
        .map_or(0, |duration| duration.as_nanos());
    Some(format!(
        "{}|{}|{modified}",
        path.to_string_lossy(),
        metadata.len()
    ))
}

#[derive(Default, Serialize, Deserialize)]
struct Stored {
    version: u32,
    /// `path|size|modified` → measure (`None`: could not be measured).
    entries: HashMap<String, Option<Measure>>,
}

pub struct LoudnessCache {
    path: PathBuf,
    entries: Mutex<Option<HashMap<String, Option<Measure>>>>,
    busy: Mutex<HashSet<String>>,
}

impl LoudnessCache {
    pub fn new(path: PathBuf) -> Self {
        Self {
            path,
            entries: Mutex::new(None),
            busy: Mutex::new(HashSet::new()),
        }
    }

    fn with_entries<T>(&self, f: impl FnOnce(&mut HashMap<String, Option<Measure>>) -> T) -> T {
        let mut guard = self
            .entries
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let entries = guard.get_or_insert_with(|| {
            fs::read(&self.path)
                .ok()
                .and_then(|bytes| serde_json::from_slice::<Stored>(&bytes).ok())
                .map(|stored| stored.entries)
                .unwrap_or_default()
        });
        f(entries)
    }

    /// The cached measure of `song` as it is now (`None` when not measured).
    pub fn get(&self, song: &Path) -> Option<Measure> {
        let key = file_key(song)?;
        self.with_entries(|entries| entries.get(&key).copied().flatten())
    }

    /// Songs in `songs` that were never measured (and are not being measured).
    pub fn missing(&self, songs: &[PathBuf]) -> Vec<PathBuf> {
        let keys: Vec<(PathBuf, String)> = songs
            .iter()
            .filter_map(|song| file_key(song).map(|key| (song.clone(), key)))
            .collect();
        let busy = self
            .busy
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
            .clone();
        self.with_entries(|entries| {
            keys.into_iter()
                .filter(|(_, key)| !entries.contains_key(key) && !busy.contains(key))
                .map(|(song, _)| song)
                .collect()
        })
    }

    /// Claims `song` for measuring; false when another job has it.
    pub fn claim(&self, song: &Path) -> bool {
        file_key(song).is_some_and(|key| {
            self.busy
                .lock()
                .unwrap_or_else(|poison| poison.into_inner())
                .insert(key)
        })
    }

    /// Records a result (also failures, so they are not retried) and saves.
    pub fn record(&self, song: &Path, measure: Option<Measure>) {
        let Some(key) = file_key(song) else { return };
        self.busy
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
            .remove(&key);
        let stored = self.with_entries(|entries| {
            entries.insert(key, measure);
            Stored {
                version: 1,
                entries: entries.clone(),
            }
        });
        if let Ok(bytes) = serde_json::to_vec(&stored) {
            if let Some(parent) = self.path.parent() {
                let _ = fs::create_dir_all(parent);
            }
            let temporary = self.path.with_extension("json.tmp");
            if fs::write(&temporary, bytes).is_ok() {
                let _ = fs::rename(&temporary, &self.path);
            }
        }
    }
}
