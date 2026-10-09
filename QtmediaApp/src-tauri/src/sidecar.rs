use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Runtime};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::oneshot;

use crate::protocol::{parse_sidecar_line, terminal_event, StableError};

struct PendingRequest {
    action: String,
    sender: oneshot::Sender<Result<Value, StableError>>,
}

pub struct SidecarManager {
    child: Mutex<Option<CommandChild>>,
    pending: Mutex<HashMap<String, PendingRequest>>,
    activity: ActivityTracker,
    lifecycle: LifecycleTracker,
    sequence: AtomicU64,
}

#[derive(Default)]
pub struct LifecycleTracker(AtomicBool);

impl LifecycleTracker {
    pub fn begin_shutdown(&self) {
        self.0.store(true, Ordering::Release);
    }

    pub fn is_shutting_down(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}

#[derive(Default)]
pub struct ActivityTracker {
    jobs: Mutex<HashMap<String, String>>,
}

impl ActivityTracker {
    pub fn started(&self, job_id: &str, request_id: &str) {
        if let Ok(mut jobs) = self.jobs.lock() {
            jobs.insert(job_id.to_owned(), request_id.to_owned());
        }
    }

    pub fn finished(&self, job_id: &str, request_id: &str) {
        if let Ok(mut jobs) = self.jobs.lock() {
            if jobs.get(job_id).is_some_and(|owner| owner == request_id) {
                jobs.remove(job_id);
            }
        }
    }

    pub fn is_busy(&self) -> bool {
        self.jobs
            .lock()
            .map(|jobs| !jobs.is_empty())
            .unwrap_or(true)
    }

    pub fn clear(&self) {
        if let Ok(mut jobs) = self.jobs.lock() {
            jobs.clear();
        }
    }
}

pub fn request_can_recover(action: &str, error: StableError) -> bool {
    matches!(action, "inspect" | "library_list")
        && matches!(
            error,
            StableError::SidecarUnavailable | StableError::ProcessExited
        )
}

pub fn bundled_binary_sibling(
    current_executable: &Path,
    binary_name: &str,
) -> Result<PathBuf, StableError> {
    current_executable
        .parent()
        .map(|directory| directory.join(binary_name))
        .ok_or(StableError::SidecarUnavailable)
}

impl SidecarManager {
    pub fn start<R: Runtime>(
        app: AppHandle<R>,
        library_root: &Path,
    ) -> Result<Arc<Self>, StableError> {
        let root = library_root
            .to_str()
            .ok_or(StableError::SidecarUnavailable)?;
        let ffmpeg_name = if cfg!(windows) {
            "ffmpeg.exe"
        } else {
            "ffmpeg"
        };
        let current_executable =
            std::env::current_exe().map_err(|_| StableError::SidecarUnavailable)?;
        let ffmpeg = bundled_binary_sibling(&current_executable, ffmpeg_name)?;
        if !ffmpeg.is_file() {
            return Err(StableError::SidecarUnavailable);
        }
        let command = app
            .shell()
            .sidecar("qtmedia-engine")
            .map_err(|_| StableError::SidecarUnavailable)?
            .args(["--library-root", root])
            .env("QTMEDIA_FFMPEG", ffmpeg);
        let (mut events, child) = command
            .spawn()
            .map_err(|_| StableError::SidecarUnavailable)?;
        let manager = Arc::new(Self {
            child: Mutex::new(Some(child)),
            pending: Mutex::new(HashMap::new()),
            activity: ActivityTracker::default(),
            lifecycle: LifecycleTracker::default(),
            sequence: AtomicU64::new(1),
        });

        let reader = Arc::clone(&manager);
        tauri::async_runtime::spawn(async move {
            while let Some(process_event) = events.recv().await {
                match process_event {
                    CommandEvent::Stdout(bytes) if bytes.iter().all(u8::is_ascii_whitespace) => {}
                    CommandEvent::Stdout(bytes) => match std::str::from_utf8(&bytes)
                        .map_err(|_| StableError::MalformedOutput)
                        .and_then(parse_sidecar_line)
                    {
                        Ok(event) => {
                            reader.observe_activity(&event);
                            let _ = app.emit("desktop-event", event.frontend_payload.clone());
                            reader.resolve(
                                &event.request_id,
                                &event.event_name,
                                event.frontend_payload,
                            );
                        }
                        Err(error) => reader.process_failed(&app, error),
                    },
                    CommandEvent::Terminated(_) => {
                        if let Ok(mut child) = reader.child.lock() {
                            child.take();
                        }
                        if !reader.lifecycle.is_shutting_down() {
                            reader.process_failed(&app, StableError::ProcessExited);
                        }
                        break;
                    }
                    CommandEvent::Error(_) => {
                        if !reader.lifecycle.is_shutting_down() {
                            reader.process_failed(&app, StableError::SidecarUnavailable);
                        }
                        break;
                    }
                    CommandEvent::Stderr(_) => {}
                    _ => {}
                }
            }
        });
        Ok(manager)
    }

    fn observe_activity(&self, event: &crate::protocol::SidecarEvent) {
        let job_id = event.frontend_payload.get("jobId").and_then(Value::as_str);
        match (event.event_name.as_str(), job_id) {
            ("download_started", Some(job_id)) => self.activity.started(job_id, &event.request_id),
            ("download_completed" | "download_cancelled" | "error", Some(job_id)) => {
                self.activity.finished(job_id, &event.request_id)
            }
            _ => {}
        }
    }

    pub fn is_busy(&self) -> bool {
        let has_pending_work = self
            .pending
            .lock()
            .map(|requests| {
                requests.values().any(|request| {
                    matches!(request.action.as_str(), "inspect" | "download" | "cancel")
                })
            })
            .unwrap_or(true);
        has_pending_work || self.activity.is_busy()
    }

    fn resolve(&self, request_id: &str, event_name: &str, payload: Value) {
        let pending = {
            let mut requests = match self.pending.lock() {
                Ok(requests) => requests,
                Err(_) => return,
            };
            let should_resolve = requests
                .get(request_id)
                .is_some_and(|request| terminal_event(&request.action, event_name));
            should_resolve
                .then(|| requests.remove(request_id))
                .flatten()
        };
        if let Some(pending) = pending {
            let _ = pending.sender.send(Ok(payload));
        }
    }

    fn process_failed<R: Runtime>(&self, app: &AppHandle<R>, error: StableError) {
        self.lifecycle.begin_shutdown();
        if let Ok(mut child) = self.child.lock() {
            if let Some(child) = child.take() {
                let _ = child.kill();
            }
        }
        self.activity.clear();
        let pending = self
            .pending
            .lock()
            .map(|mut requests| requests.drain().map(|(_, value)| value).collect::<Vec<_>>())
            .unwrap_or_default();
        let had_pending = !pending.is_empty();
        for request in pending {
            let _ = request.sender.send(Err(error));
        }
        if !had_pending {
            let _ = app.emit(
                "desktop-event",
                json!({"event": "error", "code": "sidecar_unavailable"}),
            );
        }
    }

    pub async fn request(&self, action: &str, payload: Value) -> Result<Value, StableError> {
        if !matches!(
            action,
            "probe" | "inspect" | "download" | "cancel" | "library_list"
        ) {
            return Err(StableError::InvalidRequest);
        }
        let request_id = format!("request-{}", self.sequence.fetch_add(1, Ordering::Relaxed));
        let mut message = match payload {
            Value::Object(fields) => fields,
            _ => return Err(StableError::InvalidRequest),
        };
        message.insert("id".into(), Value::String(request_id.clone()));
        message.insert("action".into(), Value::String(action.to_owned()));
        let encoded =
            serde_json::to_vec(&Value::Object(message)).map_err(|_| StableError::InvalidRequest)?;
        let (sender, receiver) = oneshot::channel();
        self.pending
            .lock()
            .map_err(|_| StableError::SidecarUnavailable)?
            .insert(
                request_id.clone(),
                PendingRequest {
                    action: action.to_owned(),
                    sender,
                },
            );

        let write_result = self
            .child
            .lock()
            .map_err(|_| StableError::SidecarUnavailable)?
            .as_mut()
            .ok_or(StableError::SidecarUnavailable)?
            .write(&[encoded.as_slice(), b"\n"].concat());
        if write_result.is_err() {
            if let Ok(mut pending) = self.pending.lock() {
                pending.remove(&request_id);
            }
            return Err(StableError::SidecarUnavailable);
        }

        tokio::time::timeout(Duration::from_secs(120), receiver)
            .await
            .map_err(|_| StableError::RequestTimeout)?
            .map_err(|_| StableError::SidecarUnavailable)?
    }

    pub fn shutdown(&self) {
        self.lifecycle.begin_shutdown();
        if let Ok(mut child) = self.child.lock() {
            if let Some(child) = child.take() {
                let _ = child.kill();
            }
        }
    }
}

impl Drop for SidecarManager {
    fn drop(&mut self) {
        self.lifecycle.begin_shutdown();
        if let Ok(child) = self.child.get_mut() {
            if let Some(child) = child.take() {
                let _ = child.kill();
            }
        }
    }
}
