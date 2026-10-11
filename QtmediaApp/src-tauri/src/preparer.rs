//! Runs the bundled ffprobe/ffmpeg to make library videos playable (see
//! `playback.rs` for the decisions). One job per prepared copy; progress and
//! results go to the webview as `playback-prepare` events. Copies live in the
//! app's local data folder and are pruned to [`CACHE_LIMIT_BYTES`], oldest
//! first.

use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;
use serde_json::{json, Value};

use crate::paths::resolve_library_entry;
use crate::playback::{
    cache_name, ffmpeg_args, parse_probe, parse_progress, plan, Encoder, Plan, Probe, Support,
};

/// Prepared copies kept on disk before the oldest are removed.
pub const CACHE_LIMIT_BYTES: u64 = 20 * 1024 * 1024 * 1024;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// What the player should do with a library video.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum Prepared {
    /// Play the library file itself.
    Direct,
    /// A prepared copy exists: play `url` (a `qtmedia://` path).
    Ready { url: String },
    /// Being prepared; follow `playback-prepare` events with this `id`.
    Preparing { id: String, mode: &'static str },
}

pub type Emit = Arc<dyn Fn(Value) + Send + Sync>;

struct Job {
    child: Arc<Mutex<Option<Child>>>,
    cancelled: Arc<AtomicBool>,
}

pub struct Preparer {
    ffmpeg: PathBuf,
    ffprobe: PathBuf,
    cache_dir: PathBuf,
    jobs: Arc<Mutex<HashMap<String, Job>>>,
    emit: Emit,
}

fn command(program: &Path) -> Command {
    #[allow(unused_mut)]
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

fn url_for(name: &str) -> String {
    format!("playback/{name}.mp4")
}

impl Preparer {
    pub fn new(ffmpeg: PathBuf, ffprobe: PathBuf, cache_dir: PathBuf, emit: Emit) -> Self {
        Self {
            ffmpeg,
            ffprobe,
            cache_dir,
            jobs: Arc::new(Mutex::new(HashMap::new())),
            emit,
        }
    }

    pub fn cache_dir(&self) -> &Path {
        &self.cache_dir
    }

    fn probe(&self, path: &Path) -> Result<Probe, &'static str> {
        let output = command(&self.ffprobe)
            .args([
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
            ])
            .arg(path)
            .stdin(Stdio::null())
            .stderr(Stdio::null())
            .output()
            .map_err(|_| "playback_unavailable")?;
        if !output.status.success() {
            return Err("playback_unsupported");
        }
        parse_probe(&String::from_utf8_lossy(&output.stdout)).ok_or("playback_unsupported")
    }

    /// Decides how `relative` (a library `video/…` path) plays, starting a
    /// conversion job when needed.
    pub fn prepare(
        &self,
        root: &Path,
        relative: &str,
        support: Support,
    ) -> Result<Prepared, &'static str> {
        if !relative.starts_with("video/") {
            return Err("unsafe_path");
        }
        let path = resolve_library_entry(root, relative).map_err(|_| "unsafe_path")?;
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        let metadata = fs::metadata(&path).map_err(|_| "not_found")?;
        let modified = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
            .map_or(0, |duration| duration.as_nanos());
        let name = cache_name(relative, metadata.len(), modified);
        let ready = self.cache_dir.join(format!("{name}.mp4"));
        if ready.is_file() {
            // Recently used copies survive pruning longest.
            let _ = fs::File::options()
                .append(true)
                .open(&ready)
                .and_then(|file| file.set_modified(SystemTime::now()));
            return Ok(Prepared::Ready {
                url: url_for(&name),
            });
        }
        if let Some(mode) = self.running_mode(&name) {
            return Ok(Prepared::Preparing { id: name, mode });
        }
        let probe = self.probe(&path)?;
        let plan = plan(&extension, &probe, support).map_err(|_| "playback_unsupported")?;
        if plan == Plan::Direct {
            return Ok(Prepared::Direct);
        }
        self.start(name.clone(), path, probe, plan)?;
        Ok(Prepared::Preparing {
            id: name,
            mode: plan.label(),
        })
    }

    fn running_mode(&self, name: &str) -> Option<&'static str> {
        self.jobs
            .lock()
            .ok()?
            .contains_key(name)
            .then_some("preparing")
    }

    /// Stops a running job and removes its partial file.
    pub fn cancel(&self, id: &str) {
        let job = self.jobs.lock().ok().and_then(|mut jobs| jobs.remove(id));
        if let Some(job) = job {
            job.cancelled.store(true, Ordering::SeqCst);
            if let Ok(mut child) = job.child.lock() {
                if let Some(child) = child.as_mut() {
                    let _ = child.kill();
                }
            }
        }
    }

    /// Stops every job (app exit).
    pub fn shutdown(&self) {
        let ids: Vec<String> = self
            .jobs
            .lock()
            .map(|jobs| jobs.keys().cloned().collect())
            .unwrap_or_default();
        for id in ids {
            self.cancel(&id);
        }
    }

    fn start(
        &self,
        name: String,
        input: PathBuf,
        probe: Probe,
        plan: Plan,
    ) -> Result<(), &'static str> {
        fs::create_dir_all(&self.cache_dir).map_err(|_| "storage_unavailable")?;
        let job = Job {
            child: Arc::new(Mutex::new(None)),
            cancelled: Arc::new(AtomicBool::new(false)),
        };
        let child_slot = job.child.clone();
        let cancelled = job.cancelled.clone();
        self.jobs
            .lock()
            .map_err(|_| "playback_unavailable")?
            .insert(name.clone(), job);
        let ffmpeg = self.ffmpeg.clone();
        let cache_dir = self.cache_dir.clone();
        let jobs = self.jobs.clone();
        let emit = self.emit.clone();
        std::thread::Builder::new()
            .name("qtmedia-playback-prepare".into())
            .spawn(move || {
                let part = cache_dir.join(format!("{name}.mp4.part"));
                let ready = cache_dir.join(format!("{name}.mp4"));
                let encode_video = matches!(plan, Plan::Transcode { video: true, .. });
                let encoders: &[Encoder] = if encode_video {
                    &[Encoder::Nvenc, Encoder::X264]
                } else {
                    &[Encoder::X264]
                };
                let mut ok = false;
                for encoder in encoders {
                    if cancelled.load(Ordering::SeqCst) {
                        break;
                    }
                    let args = ffmpeg_args(&input, &part, plan, &probe, *encoder);
                    ok = run(
                        &ffmpeg,
                        &args,
                        &child_slot,
                        &cancelled,
                        probe.duration_seconds,
                        &|percent| {
                            emit(json!({"type": "progress", "id": name, "percent": percent}));
                        },
                    );
                    if ok {
                        break;
                    }
                }
                let cancelled_now = cancelled.load(Ordering::SeqCst);
                if ok && !cancelled_now && fs::rename(&part, &ready).is_ok() {
                    prune(&cache_dir, CACHE_LIMIT_BYTES, &ready);
                    emit(json!({"type": "ready", "id": name, "url": url_for(&name)}));
                } else {
                    let _ = fs::remove_file(&part);
                    if !cancelled_now {
                        emit(
                            json!({"type": "error", "id": name, "code": "playback_prepare_failed"}),
                        );
                    }
                }
                if let Ok(mut jobs) = jobs.lock() {
                    jobs.remove(&name);
                }
            })
            .map(|_| ())
            .map_err(|_| "playback_unavailable")
    }
}

/// Runs ffmpeg, reporting whole-percent progress; true on success.
fn run(
    ffmpeg: &Path,
    args: &[std::ffi::OsString],
    slot: &Arc<Mutex<Option<Child>>>,
    cancelled: &AtomicBool,
    duration: Option<f64>,
    progress: &dyn Fn(f64),
) -> bool {
    let Ok(mut child) = command(ffmpeg)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    else {
        return false;
    };
    let stdout = child.stdout.take();
    if let Ok(mut guard) = slot.lock() {
        *guard = Some(child);
    }
    if cancelled.load(Ordering::SeqCst) {
        if let Ok(mut guard) = slot.lock() {
            if let Some(child) = guard.as_mut() {
                let _ = child.kill();
            }
        }
    }
    let mut last = -1.0;
    if let Some(stdout) = stdout {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(percent) = parse_progress(&line, duration) {
                let whole = percent.floor();
                if whole > last {
                    last = whole;
                    progress(whole);
                }
            }
        }
    }
    let status = slot
        .lock()
        .ok()
        .and_then(|mut guard| guard.take())
        .and_then(|mut child| child.wait().ok());
    status.is_some_and(|status| status.success())
}

/// Removes the least recently used copies until the cache fits `limit`,
/// never touching `keep` (the copy just made) or unrelated files.
pub fn prune(cache_dir: &Path, limit: u64, keep: &Path) {
    let Ok(entries) = fs::read_dir(cache_dir) else {
        return;
    };
    let mut copies: Vec<(SystemTime, u64, PathBuf)> = entries
        .filter_map(Result::ok)
        .filter(|entry| {
            entry
                .file_name()
                .to_str()
                .is_some_and(crate::playback::is_cache_file_name)
        })
        .filter_map(|entry| {
            let metadata = entry.metadata().ok()?;
            Some((
                metadata.modified().unwrap_or(UNIX_EPOCH),
                metadata.len(),
                entry.path(),
            ))
        })
        .collect();
    let mut total: u64 = copies.iter().map(|(_, size, _)| size).sum();
    copies.sort_by_key(|(modified, _, _)| *modified);
    for (_, size, path) in copies {
        if total <= limit {
            break;
        }
        if path == keep {
            continue;
        }
        if fs::remove_file(&path).is_ok() {
            total -= size;
        }
    }
}
