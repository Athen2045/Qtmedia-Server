use std::collections::HashMap;
use std::fmt;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

const KNOWN_EVENTS: &[&str] = &[
    "ready",
    "inspection_started",
    "inspection_ready",
    "download_started",
    "download_progress",
    "download_completed",
    "cancellation_requested",
    "download_cancelled",
    "library_changed",
    "error",
];

const PRIVATE_FIELDS: &[&str] = &[
    "url",
    "media_url",
    "source_url",
    "cookies",
    "provider_response",
    "raw_exception",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StableError {
    #[serde(rename = "protocol_error")]
    MalformedOutput,
    UnsafeOutput,
    SidecarUnavailable,
    #[serde(rename = "sidecar_exited")]
    ProcessExited,
    RequestTimeout,
    InvalidRequest,
    UnsafePath,
    NotFound,
    #[serde(rename = "storage_busy")]
    StorageBusy,
    #[serde(rename = "storage_unavailable")]
    StorageUnavailable,
}

impl fmt::Display for StableError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let value = serde_json::to_value(self).unwrap_or(Value::String("operation_failed".into()));
        formatter.write_str(value.as_str().unwrap_or("operation_failed"))
    }
}

impl std::error::Error for StableError {}

impl From<crate::paths::PathError> for StableError {
    fn from(error: crate::paths::PathError) -> Self {
        match error {
            crate::paths::PathError::UnsafePath => Self::UnsafePath,
            crate::paths::PathError::NotFound => Self::NotFound,
            crate::paths::PathError::StorageUnavailable => Self::SidecarUnavailable,
        }
    }
}

#[derive(Debug, Deserialize)]
struct WireEvent {
    id: String,
    event: String,
    #[serde(flatten)]
    payload: Map<String, Value>,
}

#[derive(Debug, Clone)]
pub struct SidecarEvent {
    pub request_id: String,
    pub event_name: String,
    pub frontend_payload: Value,
}

fn camel_key(key: &str) -> &str {
    match key {
        "media_id" => "mediaId",
        "job_id" => "jobId",
        "duration_seconds" => "durationSeconds",
        "bitrate_kbps" => "bitrateKbps",
        "downloaded_bytes" => "downloadedBytes",
        "total_bytes" => "totalBytes",
        "relative_path" => "relativePath",
        "media_type" => "mediaType",
        "size_bytes" => "sizeBytes",
        "modified_at" => "modifiedAt",
        "artwork_path" => "artworkPath",
        value => value,
    }
}

fn transform(value: Value) -> Result<Value, StableError> {
    match value {
        Value::Object(fields) => {
            let mut transformed = Map::new();
            for (key, value) in fields {
                if PRIVATE_FIELDS.contains(&key.as_str()) {
                    return Err(StableError::UnsafeOutput);
                }
                transformed.insert(camel_key(&key).to_owned(), transform(value)?);
            }
            Ok(Value::Object(transformed))
        }
        Value::Array(items) => items
            .into_iter()
            .map(transform)
            .collect::<Result<Vec<_>, _>>()
            .map(Value::Array),
        other => Ok(other),
    }
}

pub fn parse_sidecar_line(line: &str) -> Result<SidecarEvent, StableError> {
    let wire: WireEvent = serde_json::from_str(line).map_err(|_| StableError::MalformedOutput)?;
    if wire.id.trim().is_empty() || !KNOWN_EVENTS.contains(&wire.event.as_str()) {
        return Err(StableError::MalformedOutput);
    }
    let mut frontend = Map::new();
    frontend.insert("event".into(), Value::String(wire.event.clone()));
    for (key, value) in wire.payload {
        if PRIVATE_FIELDS.contains(&key.as_str()) {
            return Err(StableError::UnsafeOutput);
        }
        frontend.insert(camel_key(&key).to_owned(), transform(value)?);
    }
    Ok(SidecarEvent {
        request_id: wire.id,
        event_name: wire.event,
        frontend_payload: Value::Object(frontend),
    })
}

pub fn terminal_event(action: &str, event: &str) -> bool {
    if event == "error" {
        return true;
    }
    matches!(
        (action, event),
        ("probe", "ready")
            | ("inspect", "inspection_ready")
            | ("download", "download_started")
            | ("cancel", "cancellation_requested")
            | ("library_list", "library_changed")
    )
}

#[derive(Default)]
pub struct RequestTracker {
    actions: HashMap<String, String>,
}

impl RequestTracker {
    pub fn insert(&mut self, request_id: &str, action: &str) -> Result<(), StableError> {
        if request_id.trim().is_empty() || self.actions.contains_key(request_id) {
            return Err(StableError::InvalidRequest);
        }
        self.actions
            .insert(request_id.to_owned(), action.to_owned());
        Ok(())
    }

    pub fn is_terminal(&self, request_id: &str, event: &str) -> bool {
        self.actions
            .get(request_id)
            .is_some_and(|action| terminal_event(action, event))
    }

    pub fn take(&mut self, request_id: &str) -> Option<String> {
        self.actions.remove(request_id)
    }
}
