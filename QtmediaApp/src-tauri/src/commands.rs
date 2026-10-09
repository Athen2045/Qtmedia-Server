use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;

use crate::paths::{resolve_artwork_entry, resolve_library_entry};
use crate::protocol::StableError;
use crate::settings::{save_preference, LibraryLocation, LibraryPreference};
use crate::sidecar::{request_can_recover, SidecarManager};

struct ActiveLibrary {
    sidecar: Arc<SidecarManager>,
    root: PathBuf,
}

pub struct AppState {
    active: Mutex<ActiveLibrary>,
    default_root: PathBuf,
    preference_path: PathBuf,
    switching: AtomicBool,
}

impl AppState {
    pub fn new(
        sidecar: Arc<SidecarManager>,
        root: PathBuf,
        default_root: PathBuf,
        preference_path: PathBuf,
    ) -> Self {
        Self {
            active: Mutex::new(ActiveLibrary { sidecar, root }),
            default_root,
            preference_path,
            switching: AtomicBool::new(false),
        }
    }

    fn snapshot(&self) -> Result<(Arc<SidecarManager>, PathBuf), StableError> {
        self.active
            .lock()
            .map(|active| (Arc::clone(&active.sidecar), active.root.clone()))
            .map_err(|_| StableError::StorageUnavailable)
    }

    fn sidecar(&self) -> Result<Arc<SidecarManager>, StableError> {
        self.snapshot().map(|(sidecar, _)| sidecar)
    }

    fn ensure_not_switching(&self) -> Result<(), StableError> {
        (!self.switching.load(Ordering::Acquire))
            .then_some(())
            .ok_or(StableError::StorageBusy)
    }

    async fn request_with_recovery(
        &self,
        app: &AppHandle,
        action: &str,
        payload: Value,
    ) -> Result<Value, StableError> {
        let (sidecar, root) = self.snapshot()?;
        match sidecar.request(action, payload.clone()).await {
            Ok(value) => Ok(value),
            Err(error) if request_can_recover(action, error) => {
                let replacement = self.recover_sidecar(app, &sidecar, &root).await?;
                replacement.request(action, payload).await
            }
            Err(error) => Err(error),
        }
    }

    async fn recover_sidecar(
        &self,
        app: &AppHandle,
        failed: &Arc<SidecarManager>,
        root: &std::path::Path,
    ) -> Result<Arc<SidecarManager>, StableError> {
        self.switching
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| StableError::StorageBusy)?;
        let _guard = SwitchGuard(&self.switching);
        let replacement = SidecarManager::start(app.clone(), root)?;
        if replacement.request("probe", json!({})).await.is_err() {
            replacement.shutdown();
            return Err(StableError::SidecarUnavailable);
        }

        let installed = {
            let mut active = self
                .active
                .lock()
                .map_err(|_| StableError::StorageUnavailable)?;
            if Arc::ptr_eq(&active.sidecar, failed) {
                active.sidecar = Arc::clone(&replacement);
                true
            } else {
                false
            }
        };
        if installed {
            failed.shutdown();
            Ok(replacement)
        } else {
            replacement.shutdown();
            self.sidecar()
        }
    }
}

struct SwitchGuard<'a>(&'a AtomicBool);

impl Drop for SwitchGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LibraryEntry {
    pub relative_path: String,
    pub media_type: String,
    pub extension: String,
    pub size_bytes: u64,
    pub modified_at: f64,
    pub duration_seconds: Option<f64>,
    pub artwork_path: Option<String>,
}

fn reject_error_event(value: serde_json::Value) -> Result<serde_json::Value, StableError> {
    if value.get("event").and_then(|event| event.as_str()) == Some("error") {
        Err(StableError::InvalidRequest)
    } else {
        Ok(value)
    }
}

#[tauri::command]
pub async fn inspect_link(
    app: AppHandle,
    url: String,
    state: State<'_, AppState>,
) -> Result<(), StableError> {
    if url.len() > 4096 || url.trim().is_empty() {
        return Err(StableError::InvalidRequest);
    }
    state.ensure_not_switching()?;
    let _ = state
        .request_with_recovery(&app, "inspect", json!({"url": url}))
        .await?;
    Ok(())
}

#[tauri::command]
pub async fn start_download(
    media_id: String,
    format_key: String,
    state: State<'_, AppState>,
) -> Result<(), StableError> {
    if media_id.trim().is_empty() || format_key.trim().is_empty() || format_key.len() > 256 {
        return Err(StableError::InvalidRequest);
    }
    state.ensure_not_switching()?;
    let sidecar = state.sidecar()?;
    let _ = sidecar
        .request(
            "download",
            json!({"media_id": media_id, "format_key": format_key}),
        )
        .await?;
    Ok(())
}

#[tauri::command]
pub async fn cancel_download(
    job_id: String,
    state: State<'_, AppState>,
) -> Result<(), StableError> {
    if job_id.is_empty() {
        return Err(StableError::InvalidRequest);
    }
    let sidecar = state.sidecar()?;
    let _ = sidecar.request("cancel", json!({"job_id": job_id})).await?;
    Ok(())
}

#[tauri::command]
pub async fn list_library(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<Vec<LibraryEntry>, StableError> {
    let response = reject_error_event(
        state
            .request_with_recovery(&app, "library_list", json!({}))
            .await?,
    )?;
    serde_json::from_value(
        response
            .get("entries")
            .cloned()
            .unwrap_or_else(|| json!([])),
    )
    .map_err(|_| StableError::MalformedOutput)
}

#[tauri::command]
pub fn open_media(relative_path: String, state: State<'_, AppState>) -> Result<(), StableError> {
    let (_, root) = state.snapshot()?;
    let path = resolve_library_entry(&root, &relative_path)?;
    tauri_plugin_opener::open_path(path, None::<&str>).map_err(|_| StableError::NotFound)
}

#[tauri::command]
pub fn open_library(state: State<'_, AppState>) -> Result<(), StableError> {
    let (_, root) = state.snapshot()?;
    tauri_plugin_opener::open_path(root, None::<&str>).map_err(|_| StableError::NotFound)
}

#[tauri::command]
pub fn read_artwork(
    relative_path: String,
    state: State<'_, AppState>,
) -> Result<String, StableError> {
    let (_, root) = state.snapshot()?;
    let path = resolve_artwork_entry(&root, &relative_path)?;
    let metadata = std::fs::metadata(&path).map_err(|_| StableError::NotFound)?;
    if metadata.len() > 8 * 1024 * 1024 {
        return Err(StableError::UnsafePath);
    }
    let mime = match path
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
    {
        Some(extension) if matches!(extension.as_str(), "jpg" | "jpeg") => "image/jpeg",
        Some(extension) if extension == "png" => "image/png",
        Some(extension) if extension == "webp" => "image/webp",
        _ => return Err(StableError::UnsafePath),
    };
    let bytes = std::fs::read(path).map_err(|_| StableError::NotFound)?;
    let encoded = base64::engine::general_purpose::STANDARD.encode(bytes);
    Ok(format!("data:{mime};base64,{encoded}"))
}

#[tauri::command]
pub fn window_minimize(window: WebviewWindow) -> Result<(), StableError> {
    window.minimize().map_err(|_| StableError::InvalidRequest)
}

#[tauri::command]
pub fn window_toggle_maximize(window: WebviewWindow) -> Result<(), StableError> {
    let maximized = window
        .is_maximized()
        .map_err(|_| StableError::InvalidRequest)?;
    if maximized {
        window.unmaximize()
    } else {
        window.maximize()
    }
    .map_err(|_| StableError::InvalidRequest)
}

#[tauri::command]
pub fn window_close(window: WebviewWindow, state: State<'_, AppState>) -> Result<(), StableError> {
    state.sidecar()?.shutdown();
    window.close().map_err(|_| StableError::InvalidRequest)
}

#[tauri::command]
pub fn get_download_location(state: State<'_, AppState>) -> Result<LibraryLocation, StableError> {
    let (_, root) = state.snapshot()?;
    Ok(LibraryLocation::new(
        root.clone(),
        root == state.default_root,
    ))
}

async fn switch_library(
    app: &AppHandle,
    state: &AppState,
    root: PathBuf,
    preference: LibraryPreference,
) -> Result<LibraryLocation, StableError> {
    crate::paths::prepare_library(&root)?;
    let replacement = SidecarManager::start(app.clone(), &root)?;
    if replacement.request("probe", json!({})).await.is_err() {
        replacement.shutdown();
        return Err(StableError::SidecarUnavailable);
    }
    if save_preference(&state.preference_path, &preference).is_err() {
        replacement.shutdown();
        return Err(StableError::StorageUnavailable);
    }
    let previous = {
        let mut active = state
            .active
            .lock()
            .map_err(|_| StableError::StorageUnavailable)?;
        std::mem::replace(
            &mut *active,
            ActiveLibrary {
                sidecar: replacement,
                root: root.clone(),
            },
        )
    };
    previous.sidecar.shutdown();
    Ok(LibraryLocation::new(
        root.clone(),
        root == state.default_root,
    ))
}

fn begin_switch(state: &AppState) -> Result<SwitchGuard<'_>, StableError> {
    state
        .switching
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| StableError::StorageBusy)?;
    let guard = SwitchGuard(&state.switching);
    if state.sidecar()?.is_busy() {
        return Err(StableError::StorageBusy);
    }
    Ok(guard)
}

#[tauri::command]
pub async fn choose_download_location(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<Option<LibraryLocation>, StableError> {
    let _guard = begin_switch(&state)?;
    let selection = app
        .dialog()
        .file()
        .set_title("Choose where Qtmedia stores downloads")
        .blocking_pick_folder();
    let Some(selection) = selection else {
        return Ok(None);
    };
    let selected = selection.into_path().map_err(|_| StableError::UnsafePath)?;
    let root = crate::paths::selected_library_root(&selected)?;
    let preference = LibraryPreference::custom(root.clone());
    switch_library(&app, &state, root, preference)
        .await
        .map(Some)
}

#[tauri::command]
pub async fn use_default_download_location(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<LibraryLocation, StableError> {
    let _guard = begin_switch(&state)?;
    switch_library(
        &app,
        &state,
        state.default_root.clone(),
        LibraryPreference::default(),
    )
    .await
}

pub fn main_window<R: tauri::Runtime>(
    manager: &impl Manager<R>,
) -> Option<tauri::WebviewWindow<R>> {
    manager.get_webview_window("main")
}
