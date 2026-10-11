//! Tauri commands for the native audio engine. Paths are library-relative
//! (`audio/…` only) and resolved inside the active library; the webview never
//! sends absolute paths. Errors are stable codes (`unsafe_path`,
//! `audio_unavailable`, `invalid_request`, `storage_unavailable`).

use std::sync::Arc;

use serde_json::Value;
use tauri::State;

use crate::audio::engine::Command;
use crate::audio::service::{device_json, resolve_audio_path, AudioService};
use crate::commands::AppState;
use crate::settings::{save_audio, validate_audio, AudioPreference, SettingsError};

type Audio<'a> = State<'a, Arc<AudioService>>;

fn library_song(state: &AppState, relative_path: &str) -> Result<std::path::PathBuf, String> {
    let root = state.library_root().map_err(|error| error.to_string())?;
    resolve_audio_path(&root, relative_path).map_err(|_| "unsafe_path".to_owned())
}

fn finite_seconds(seconds: f64) -> Result<f64, String> {
    (seconds.is_finite() && seconds >= 0.0)
        .then_some(seconds)
        .ok_or_else(|| "invalid_request".to_owned())
}

#[tauri::command]
pub fn audio_play(
    relative_path: String,
    start_seconds: Option<f64>,
    state: State<'_, AppState>,
    audio: Audio<'_>,
) -> Result<(), String> {
    let path = library_song(&state, &relative_path)?;
    let start_seconds = finite_seconds(start_seconds.unwrap_or(0.0))?;
    audio
        .send(Command::Play {
            path,
            start_seconds,
        })
        .map_err(str::to_owned)
}

#[tauri::command]
pub fn audio_pause(audio: Audio<'_>) {
    audio.send_if_running(Command::Pause);
}

#[tauri::command]
pub fn audio_resume(audio: Audio<'_>) {
    audio.send_if_running(Command::Resume);
}

#[tauri::command]
pub fn audio_seek(seconds: f64, audio: Audio<'_>) -> Result<(), String> {
    audio.send_if_running(Command::Seek(finite_seconds(seconds)?));
    Ok(())
}

#[tauri::command]
pub fn audio_stop(audio: Audio<'_>) {
    audio.send_if_running(Command::Stop);
}

/// Releases the device now (the video player opened); playback stays paused.
#[tauri::command]
pub fn audio_release(audio: Audio<'_>) {
    audio.send_if_running(Command::Release);
}

#[tauri::command]
pub fn audio_set_volume(volume: f64, audio: Audio<'_>) -> Result<(), String> {
    if !(0.0..=1.0).contains(&volume) {
        return Err("invalid_request".to_owned());
    }
    audio.set_volume(volume as f32);
    Ok(())
}

/// Queues the track that follows, for gapless playback (`null` clears it).
#[tauri::command]
pub fn audio_set_next(
    relative_path: Option<String>,
    state: State<'_, AppState>,
    audio: Audio<'_>,
) -> Result<(), String> {
    let next = match relative_path {
        Some(relative) => Some(library_song(&state, &relative)?),
        None => None,
    };
    audio.send_if_running(Command::SetNext(next));
    Ok(())
}

#[tauri::command]
pub async fn audio_devices(audio: Audio<'_>) -> Result<Vec<Value>, String> {
    let audio = Arc::clone(&audio);
    tauri::async_runtime::spawn_blocking(move || audio.devices())
        .await
        .map_err(|_| "audio_unavailable".to_owned())?
        .map(|devices| devices.iter().map(device_json).collect())
        .map_err(str::to_owned)
}

#[tauri::command]
pub fn audio_get_settings(audio: Audio<'_>) -> AudioPreference {
    audio.preference()
}

#[tauri::command]
pub fn audio_set_settings(
    settings: AudioPreference,
    state: State<'_, AppState>,
    audio: Audio<'_>,
) -> Result<AudioPreference, String> {
    let settings = validate_audio(settings).map_err(|_| "invalid_request".to_owned())?;
    save_audio(state.preference_path(), settings.clone()).map_err(|error| match error {
        SettingsError::InvalidPreference => "invalid_request".to_owned(),
        SettingsError::StorageUnavailable => "storage_unavailable".to_owned(),
    })?;
    audio.set_preference(settings.clone());
    Ok(settings)
}
