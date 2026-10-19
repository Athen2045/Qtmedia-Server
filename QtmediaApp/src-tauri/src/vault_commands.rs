//! Tauri side of the Private folder: the unlock session (key in memory only,
//! auto-lock after 10 minutes idle), commands, the background job that moves
//! videos in, and streaming for the player. Storage and crypto: `vault.rs`.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use base64::Engine;
use serde::Serialize;
use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, State};

use crate::commands::AppState;
use crate::paths::{resolve_artwork_entry, resolve_library_entry};
use crate::playback::Support;
use crate::preparer::{Prepared, Preparer};
use crate::vault::{NewItem, Vault, VaultError, VaultItem, VaultKey, DEFAULT_KDF};

/// No vault activity for this long locks the folder.
pub const IDLE_LOCK: Duration = Duration::from_secs(10 * 60);
const ARTWORK_EXTENSIONS: [&str; 4] = ["jpg", "jpeg", "png", "webp"];

struct Unlocked {
    root: PathBuf,
    key: VaultKey,
}

/// The unlocked key (if any) and when the vault was last used.
pub struct VaultSession {
    unlocked: Mutex<Option<Unlocked>>,
    last_activity: Mutex<Instant>,
}

impl Default for VaultSession {
    fn default() -> Self {
        Self {
            unlocked: Mutex::new(None),
            last_activity: Mutex::new(Instant::now()),
        }
    }
}

impl VaultSession {
    fn touch(&self) {
        if let Ok(mut last) = self.last_activity.lock() {
            *last = Instant::now();
        }
    }

    /// The key for the vault of `root`, when it is unlocked (counts as use).
    pub fn key_for(&self, root: &Path) -> Option<VaultKey> {
        let key = self
            .unlocked
            .lock()
            .ok()?
            .as_ref()
            .filter(|unlocked| unlocked.root == root)
            .map(|unlocked| unlocked.key.clone());
        if key.is_some() {
            self.touch();
        }
        key
    }

    fn set(&self, root: PathBuf, key: VaultKey) {
        if let Ok(mut unlocked) = self.unlocked.lock() {
            *unlocked = Some(Unlocked { root, key });
        }
        self.touch();
    }

    /// Tests only: unlock with a key made elsewhere.
    #[doc(hidden)]
    pub fn set_for_tests(&self, root: PathBuf, key: VaultKey) {
        self.set(root, key);
    }

    /// Drops the key; returns whether it was unlocked.
    pub fn lock(&self) -> bool {
        self.unlocked
            .lock()
            .map(|mut unlocked| unlocked.take().is_some())
            .unwrap_or(false)
    }

    /// Locks when unlocked and idle for `limit`; returns whether it locked.
    pub fn lock_if_idle(&self, limit: Duration) -> bool {
        let idle = self
            .last_activity
            .lock()
            .map(|last| last.elapsed() >= limit)
            .unwrap_or(false);
        idle && self.lock()
    }

    fn is_unlocked_for(&self, root: &Path) -> bool {
        self.unlocked
            .lock()
            .map(|unlocked| {
                unlocked
                    .as_ref()
                    .is_some_and(|unlocked| unlocked.root == root)
            })
            .unwrap_or(false)
    }
}

/// Checks the idle timer every 20 s and tells the UI when it locks.
pub fn start_auto_lock(app: AppHandle) {
    std::thread::Builder::new()
        .name("qtmedia-vault-lock".into())
        .spawn(move || loop {
            std::thread::sleep(Duration::from_secs(20));
            if let Some(session) = app.try_state::<Arc<VaultSession>>() {
                if session.lock_if_idle(IDLE_LOCK) {
                    let _ = app.emit("vault-locked", json!({ "reason": "idle" }));
                }
            }
        })
        .ok();
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VaultStatus {
    pub exists: bool,
    pub unlocked: bool,
}

fn code(error: VaultError) -> String {
    error.code().to_owned()
}

fn root_of(state: &AppState) -> Result<PathBuf, String> {
    state
        .library_root()
        .map_err(|_| "storage_unavailable".to_owned())
}

fn unlocked_key(state: &AppState, session: &VaultSession) -> Result<(PathBuf, VaultKey), String> {
    let root = root_of(state)?;
    let key = session
        .key_for(&root)
        .ok_or_else(|| "vault_locked".to_owned())?;
    Ok((root, key))
}

#[tauri::command]
pub fn vault_status(
    state: State<'_, AppState>,
    session: State<'_, Arc<VaultSession>>,
) -> Result<VaultStatus, String> {
    let root = root_of(&state)?;
    Ok(VaultStatus {
        exists: Vault::of_library(&root).exists(),
        unlocked: session.is_unlocked_for(&root),
    })
}

#[tauri::command]
pub async fn vault_create(
    password: String,
    state: State<'_, AppState>,
    session: State<'_, Arc<VaultSession>>,
) -> Result<VaultStatus, String> {
    let root = root_of(&state)?;
    let vault_root = root.clone();
    let key = tauri::async_runtime::spawn_blocking(move || {
        Vault::of_library(&vault_root).create(&password, DEFAULT_KDF)
    })
    .await
    .map_err(|_| "storage_unavailable".to_owned())?
    .map_err(code)?;
    session.set(root, key);
    Ok(VaultStatus {
        exists: true,
        unlocked: true,
    })
}

#[tauri::command]
pub async fn vault_unlock(
    password: String,
    state: State<'_, AppState>,
    session: State<'_, Arc<VaultSession>>,
) -> Result<VaultStatus, String> {
    let root = root_of(&state)?;
    let vault_root = root.clone();
    let key = tauri::async_runtime::spawn_blocking(move || {
        Vault::of_library(&vault_root).unlock(&password)
    })
    .await
    .map_err(|_| "storage_unavailable".to_owned())?
    .map_err(code)?;
    session.set(root, key);
    Ok(VaultStatus {
        exists: true,
        unlocked: true,
    })
}

#[tauri::command]
pub fn vault_lock(session: State<'_, Arc<VaultSession>>) {
    session.lock();
}

#[tauri::command]
pub async fn vault_change_password(
    old: String,
    new: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let root = root_of(&state)?;
    tauri::async_runtime::spawn_blocking(move || {
        Vault::of_library(&root).change_password(&old, &new, DEFAULT_KDF)
    })
    .await
    .map_err(|_| "storage_unavailable".to_owned())?
    .map_err(code)
}

#[tauri::command]
pub fn vault_items(
    state: State<'_, AppState>,
    session: State<'_, Arc<VaultSession>>,
) -> Result<Vec<VaultItem>, String> {
    let (root, key) = unlocked_key(&state, &session)?;
    Vault::of_library(&root).items(&key).map_err(code)
}

/// A vault item's cover as a data URL (decrypted in memory only).
#[tauri::command]
pub fn vault_cover(
    id: String,
    state: State<'_, AppState>,
    session: State<'_, Arc<VaultSession>>,
) -> Result<Option<String>, String> {
    let (root, key) = unlocked_key(&state, &session)?;
    let cover = Vault::of_library(&root).cover(&key, &id).map_err(code)?;
    Ok(cover.map(|bytes| {
        let mime = if bytes.starts_with(b"\x89PNG") {
            "image/png"
        } else if bytes.len() > 12 && &bytes[8..12] == b"WEBP" {
            "image/webp"
        } else {
            "image/jpeg"
        };
        format!(
            "data:{mime};base64,{}",
            base64::engine::general_purpose::STANDARD.encode(bytes)
        )
    }))
}

#[tauri::command]
pub async fn vault_restore(
    id: String,
    state: State<'_, AppState>,
    session: State<'_, Arc<VaultSession>>,
) -> Result<String, String> {
    let (root, key) = unlocked_key(&state, &session)?;
    tauri::async_runtime::spawn_blocking(move || Vault::of_library(&root).restore(&key, &id, &root))
        .await
        .map_err(|_| "storage_unavailable".to_owned())?
        .map_err(code)
}

#[tauri::command]
pub fn vault_delete(
    id: String,
    state: State<'_, AppState>,
    session: State<'_, Arc<VaultSession>>,
) -> Result<(), String> {
    let (root, key) = unlocked_key(&state, &session)?;
    Vault::of_library(&root).delete(&key, &id).map_err(code)
}

/// Moves library videos into the vault in the background. Progress arrives
/// as `vault-progress` / `vault-added` / `vault-failed`, then `vault-done`.
#[tauri::command]
pub fn vault_add(
    relative_paths: Vec<String>,
    app: AppHandle,
    state: State<'_, AppState>,
    session: State<'_, Arc<VaultSession>>,
) -> Result<(), String> {
    state
        .ensure_not_switching()
        .map_err(|_| "storage_busy".to_owned())?;
    let (root, key) = unlocked_key(&state, &session)?;
    if relative_paths.is_empty() || relative_paths.len() > 500 {
        return Err("invalid_request".to_owned());
    }
    let session = Arc::clone(&session);
    std::thread::Builder::new()
        .name("qtmedia-vault-add".into())
        .spawn(move || {
            let preparer = app
                .try_state::<Arc<Preparer>>()
                .map(|preparer| Arc::clone(&preparer));
            for relative in relative_paths {
                let result = move_in(
                    &root,
                    &relative,
                    &key,
                    preparer.as_deref(),
                    &session,
                    |percent, stage| {
                        let _ = app.emit(
                            "vault-progress",
                            json!({ "path": relative, "percent": percent, "stage": stage }),
                        );
                    },
                );
                match result {
                    Ok(moved) => {
                        let _ = app.emit(
                            "vault-added",
                            json!({ "path": relative, "item": moved.item, "originalKept": moved.original_kept }),
                        );
                    }
                    Err(error) => {
                        let _ =
                            app.emit("vault-failed", json!({ "path": relative, "code": error }));
                    }
                }
            }
            let _ = app.emit("vault-done", json!({}));
        })
        .map(|_| ())
        .map_err(|_| "storage_unavailable".to_owned())
}

/// The playable file for a library video: the file itself, or a prepared
/// MP4 copy (made now if needed). `(path, converted, is_copy)`.
fn playable_source(
    root: &Path,
    relative: &str,
    video: &Path,
    preparer: Option<&Preparer>,
    session: &VaultSession,
) -> Result<(PathBuf, bool, bool), String> {
    let Some(preparer) = preparer else {
        return Ok((video.to_path_buf(), false, false));
    };
    let copy = |url: &str| -> PathBuf {
        preparer
            .cache_dir()
            .join(url.strip_prefix("playback/").unwrap_or(url))
    };
    match preparer.prepare(root, relative, Support { dolby: false }) {
        Ok(Prepared::Direct) => Ok((video.to_path_buf(), false, false)),
        Ok(Prepared::Ready { url }) => Ok((copy(&url), false, true)),
        Ok(Prepared::Preparing { id, mode }) => {
            let ready = preparer.cache_dir().join(format!("{id}.mp4"));
            loop {
                // A long conversion is vault activity, not idling.
                session.touch();
                if ready.is_file() && !preparer.is_running(&id) {
                    return Ok((ready, mode == "transcode", true));
                }
                if !preparer.is_running(&id) {
                    return Err("playback_unsupported".to_owned());
                }
                std::thread::sleep(Duration::from_millis(500));
            }
        }
        Err(code) => Err(code.to_owned()),
    }
}

fn move_in(
    root: &Path,
    relative: &str,
    key: &VaultKey,
    preparer: Option<&Preparer>,
    session: &VaultSession,
    mut progress: impl FnMut(u32, &'static str),
) -> Result<Moved, String> {
    if !relative.starts_with("video/") {
        return Err("unsafe_path".to_owned());
    }
    let video = resolve_library_entry(root, relative).map_err(|_| "not_found".to_owned())?;
    let name = video
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or("unsafe_path")?
        .to_owned();
    let stem = video
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or("unsafe_path")?
        .to_owned();
    progress(0, "preparing");
    let (source, converted, is_copy) = playable_source(root, relative, &video, preparer, session)?;
    let cover = ARTWORK_EXTENSIONS.iter().find_map(|extension| {
        resolve_artwork_entry(root, &format!("artwork/{stem}.{extension}")).ok()
    });
    let duration = crate::durations::measure(root, relative, preparer.map(Preparer::ffprobe));
    let mut last = u32::MAX;
    let item = Vault::of_library(root)
        .add(
            key,
            NewItem {
                source: &source,
                cover: cover.as_deref(),
                title: stem.clone(),
                original_name: name,
                duration_seconds: duration,
                converted,
            },
            |done, total| {
                session.touch();
                let percent = if total == 0 {
                    100
                } else {
                    (done * 100 / total) as u32
                };
                if percent != last {
                    last = percent;
                    progress(percent, "encrypting");
                }
            },
        )
        .map_err(code)?;
    // Only now, with the encrypted copy saved: remove every readable copy
    // for good (the Recycle Bin would keep one). Windows refuses to delete a
    // file another program has open, so retry briefly and say if it stays.
    let mut kept = !remove_with_retry(&video);
    if let Some(cover) = cover {
        kept |= !remove_with_retry(&cover);
    }
    for subtitle in crate::subtitles::files_for(root, relative) {
        kept |= !remove_with_retry(&subtitle);
    }
    if is_copy {
        kept |= !remove_with_retry(&source);
    }
    Ok(Moved {
        item,
        original_kept: kept,
    })
}

/// What `move_in` did: the vault item, and whether a readable copy could not
/// be removed (a file in use).
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Moved {
    pub item: VaultItem,
    pub original_kept: bool,
}

/// Deletes `path`, retrying for about 2 s while it is in use. True when it
/// is gone.
pub fn remove_with_retry(path: &Path) -> bool {
    for attempt in 0..10 {
        match std::fs::remove_file(path) {
            Ok(()) => return true,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return true,
            Err(_) if attempt < 9 => std::thread::sleep(Duration::from_millis(200)),
            Err(_) => {}
        }
    }
    !path.exists()
}
