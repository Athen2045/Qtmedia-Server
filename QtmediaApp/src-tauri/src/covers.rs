//! Covers for videos that have none: a frame from a pseudo-random point of
//! the video, picked once per file (15–60 % in, so it is stable across
//! launches) and saved as `artwork/<stem>.jpg`, so the library scan, renames
//! and Files "Delete" treat it like any downloaded cover. ffmpeg's
//! `thumbnail` filter chooses the most representative of ~2 s of frames
//! there, which skips black and transition frames.

use std::collections::HashSet;
use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::Mutex;

use crate::paths::resolve_library_entry;

const ARTWORK_EXTENSIONS: [&str; 4] = ["jpg", "jpeg", "png", "webp"];
/// Used when a video's duration is unknown.
const FALLBACK_SECONDS: f64 = 10.0;

/// Videos being given a cover, and ones that failed this session.
#[derive(Default)]
pub struct CoverJobs {
    busy: Mutex<HashSet<String>>,
    failed: Mutex<HashSet<String>>,
}

impl CoverJobs {
    /// Claims `relative` for generation; false when running or failed before.
    pub fn claim(&self, relative: &str) -> bool {
        let failed = self
            .failed
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        if failed.contains(relative) {
            return false;
        }
        self.busy
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
            .insert(relative.to_owned())
    }

    pub fn finish(&self, relative: &str, ok: bool) {
        self.busy
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
            .remove(relative);
        if !ok {
            self.failed
                .lock()
                .unwrap_or_else(|poison| poison.into_inner())
                .insert(relative.to_owned());
        }
    }
}

/// Where in the video (seconds) the cover is taken: 15–60 % in, chosen by a
/// hash of the path so it never changes for that file.
pub fn cover_point(relative: &str, duration: Option<f64>) -> f64 {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in relative.bytes() {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x0100_0000_01b3);
    }
    let fraction = 0.15 + 0.45 * ((hash % 10_000) as f64 / 10_000.0);
    match duration {
        Some(seconds) if seconds.is_finite() && seconds > 4.0 => seconds * fraction,
        Some(seconds) if seconds.is_finite() && seconds > 0.0 => seconds / 2.0,
        _ => FALLBACK_SECONDS,
    }
}

/// The frame filter: pick a representative frame, tone-map HDR (PQ/HLG) to
/// SDR so the cover is not grey and washed out, and cap the width.
pub fn cover_filter(transfer: Option<&str>) -> String {
    let hdr = matches!(transfer, Some("smpte2084" | "arib-std-b67"));
    let tonemap = if hdr {
        "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,"
    } else {
        ""
    };
    format!("thumbnail=48,{tonemap}scale='min(960,iw)':-2")
}

fn video_transfer(ffprobe: &Path, video: &Path) -> Option<String> {
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
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=color_transfer",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
        ])
        .arg(video)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .ok()?;
    let transfer = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    (output.status.success() && !transfer.is_empty()).then_some(transfer)
}

/// Whether the library video `relative` already has a cover.
pub fn has_cover_for(root: &Path, relative: &str) -> bool {
    Path::new(relative)
        .file_stem()
        .and_then(|stem| stem.to_str())
        .is_some_and(|stem| has_cover(root, stem))
}

fn has_cover(root: &Path, stem: &str) -> bool {
    ARTWORK_EXTENSIONS.iter().any(|extension| {
        root.join("artwork")
            .join(format!("{stem}.{extension}"))
            .exists()
    })
}

/// Saves a frame of `relative` (a library video) as its cover. Returns the
/// new `artwork/…` path, or `None` when it has a cover or ffmpeg failed.
pub fn make_cover(
    root: &Path,
    relative: &str,
    duration: Option<f64>,
    ffmpeg: &Path,
    ffprobe: Option<&Path>,
) -> Option<String> {
    if !relative.starts_with("video/") {
        return None;
    }
    let video = resolve_library_entry(root, relative).ok()?;
    let stem = video.file_stem()?.to_str()?.to_owned();
    if has_cover(root, &stem) {
        return None;
    }
    let temp_dir = root.join("temp");
    fs::create_dir_all(&temp_dir).ok()?;
    let part = temp_dir.join(format!("cover-{:016x}.jpg", {
        let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
        for byte in relative.bytes() {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x0100_0000_01b3);
        }
        hash
    }));
    let seconds = cover_point(relative, duration);
    let filter = cover_filter(
        ffprobe
            .and_then(|probe| video_transfer(probe, &video))
            .as_deref(),
    );
    let attempt = |at: f64| {
        let mut command = Command::new(ffmpeg);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        command
            .args([
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-ss",
                &format!("{at:.3}"),
                "-i",
            ])
            .arg(&video)
            .args([
                "-an",
                "-sn",
                "-vf",
                &filter,
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-f",
                "image2",
                "-c:v",
                "mjpeg",
            ])
            .arg(&part)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|status| status.success())
            && fs::metadata(&part).is_ok_and(|metadata| metadata.len() > 0)
    };
    // A point past the real end (wrong duration) gives no frame: try the start.
    let made = attempt(seconds) || attempt(0.0);
    if !made {
        let _ = fs::remove_file(&part);
        return None;
    }
    let destination = root.join("artwork").join(format!("{stem}.jpg"));
    // Never replace a cover that appeared meanwhile, and never leave one for
    // a video that went away while ffmpeg ran (moved to the Private folder,
    // deleted): it would be a readable frame named after it.
    if destination.exists() || !video.is_file() || fs::rename(&part, &destination).is_err() {
        let _ = fs::remove_file(&part);
        return None;
    }
    Some(format!("artwork/{stem}.jpg"))
}
