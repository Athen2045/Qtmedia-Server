//! Desktop glue for the native audio engine: the lazily started
//! [`AudioEngine`], the saved audio preference, the Windows device watcher,
//! and the `audio-event` payloads sent to the webview.
//!
//! The webview only ever sees library-relative paths (`audio/Song.flac`);
//! commands resolve them with [`resolve_audio_path`] before the engine opens
//! anything.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};

use super::decoder::{Codec, SourceFormat};
use super::engine::{Command, Event, Settings};
use super::format::{OutputMode, RateMismatch};
use super::output::{DeviceInfo, Transport};
use crate::paths::{resolve_library_entry, PathError};
use crate::settings::{AudioMode, AudioPreference, RateMismatchPreference};

/// A library song the engine may open: under `audio/` and inside the root.
pub fn resolve_audio_path(root: &Path, relative: &str) -> Result<PathBuf, PathError> {
    if !relative.starts_with("audio/") {
        return Err(PathError::UnsafePath);
    }
    resolve_library_entry(root, relative)
}

/// The library-relative form of an engine path (`None` outside the root).
pub fn relative_audio_path(root: &Path, path: &Path) -> Option<String> {
    let root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
    let path = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
    let relative = path.strip_prefix(&root).ok()?;
    let text = relative
        .components()
        .map(|part| part.as_os_str().to_str())
        .collect::<Option<Vec<_>>>()?
        .join("/");
    text.starts_with("audio/").then_some(text)
}

/// Engine settings for a preference and the device actually used (the saved
/// device when present, else the default).
pub fn engine_settings(preference: &AudioPreference, device: Option<String>) -> Settings {
    Settings {
        device,
        mode: match preference.mode {
            AudioMode::Shared => OutputMode::Shared,
            AudioMode::Exclusive => OutputMode::Exclusive,
        },
        rate_mismatch: match preference.rate_mismatch {
            RateMismatchPreference::Strict => RateMismatch::Strict,
            RateMismatchPreference::Resample => RateMismatch::Resample,
        },
        exclusive_volume: preference.exclusive_volume,
    }
}

/// The saved device if it is connected; otherwise follow the default.
pub fn effective_device(preference: &AudioPreference, devices: &[DeviceInfo]) -> Option<String> {
    preference
        .device_id
        .clone()
        .filter(|id| devices.iter().any(|device| &device.id == id))
}

fn transport_name(transport: Transport) -> &'static str {
    match transport {
        Transport::Wired => "wired",
        Transport::Bluetooth => "bluetooth",
        Transport::BluetoothHandsFree => "bluetoothHandsFree",
    }
}

pub fn device_json(device: &DeviceInfo) -> Value {
    json!({
        "id": device.id,
        "name": device.name,
        "transport": transport_name(device.transport),
        "isDefault": device.is_default,
    })
}

fn source_json(source: &SourceFormat) -> Value {
    json!({
        "codec": match source.codec { Codec::Flac => "flac", Codec::Mp3 => "mp3" },
        "sampleRate": source.sample_rate,
        "channels": source.channels,
        "bitsPerSample": source.bits_per_sample,
    })
}

/// The `audio-event` payload for an engine event. `device` is the output in
/// use (for the signal path); paths become library-relative.
pub fn event_payload(event: &Event, root: &Path, device: Option<&DeviceInfo>) -> Value {
    let path = |path: &Path| relative_audio_path(root, path);
    match event {
        Event::State(state) => json!({"type": "state", "state": state.as_str()}),
        Event::Position { seconds } => json!({"type": "position", "seconds": seconds}),
        Event::TrackStarted {
            path: track,
            duration,
            source,
        } => json!({
            "type": "trackStarted",
            "path": path(track),
            "durationSeconds": duration,
            "source": source_json(source),
        }),
        Event::TrackEnded { path: track } => json!({"type": "trackEnded", "path": path(track)}),
        Event::SignalPath { source, negotiated } => json!({
            "type": "signalPath",
            "source": source_json(source),
            "output": {
                "mode": match negotiated.mode { OutputMode::Shared => "shared", OutputMode::Exclusive => "exclusive" },
                "sampleRate": negotiated.output.rate,
                "channels": negotiated.output.channels,
                "bits": negotiated.output.valid_bits,
                "containerBits": negotiated.output.container_bits,
                "float": negotiated.output.float,
            },
            "bitPerfect": negotiated.bit_perfect,
            "reason": negotiated.reason.map(|reason| reason.code()),
            "device": device.map(|device| json!({"name": device.name, "transport": transport_name(device.transport)})),
        }),
        Event::DeviceOpened { .. } => json!({"type": "deviceOpened"}),
        Event::DeviceReleased => json!({"type": "deviceReleased"}),
        Event::Error { code } => json!({"type": "error", "code": code}),
    }
}

pub type Emit = Arc<dyn Fn(Value) + Send + Sync>;
pub type RootFn = Arc<dyn Fn() -> Option<PathBuf> + Send + Sync>;

struct Shared {
    preference: AudioPreference,
    devices: Vec<DeviceInfo>,
}

struct Inner {
    #[cfg(windows)]
    engine: Option<super::engine::AudioEngine>,
    #[cfg(windows)]
    watcher: Option<watcher::Watcher>,
    volume: f32,
}

/// Owns the engine for the app's lifetime. The engine and device watcher
/// start on the first audio command, so an app that never plays music runs
/// no audio threads.
pub struct AudioService {
    inner: Mutex<Inner>,
    shared: Arc<Mutex<Shared>>,
    emit: Emit,
    root: RootFn,
}

impl AudioService {
    pub fn new(preference: AudioPreference, emit: Emit, root: RootFn) -> Self {
        Self {
            inner: Mutex::new(Inner {
                #[cfg(windows)]
                engine: None,
                #[cfg(windows)]
                watcher: None,
                volume: 1.0,
            }),
            shared: Arc::new(Mutex::new(Shared {
                preference,
                devices: Vec::new(),
            })),
            emit,
            root,
        }
    }

    pub fn preference(&self) -> AudioPreference {
        self.shared
            .lock()
            .map(|shared| shared.preference.clone())
            .unwrap_or_default()
    }

    /// Output devices, default marked.
    pub fn devices(&self) -> Result<Vec<DeviceInfo>, &'static str> {
        #[cfg(windows)]
        {
            let devices = super::output::list_devices().map_err(|error| error.code())?;
            if let Ok(mut shared) = self.shared.lock() {
                shared.devices = devices.clone();
            }
            Ok(devices)
        }
        #[cfg(not(windows))]
        {
            Err("audio_unavailable")
        }
    }

    /// Sends a command, starting the engine first if needed.
    pub fn send(&self, command: Command) -> Result<(), &'static str> {
        #[cfg(windows)]
        {
            let mut inner = self.inner.lock().map_err(|_| "audio_unavailable")?;
            if let Command::SetVolume(volume) = command {
                inner.volume = volume;
            }
            if inner.engine.is_none() {
                let engine = self.start_engine(inner.volume)?;
                inner.watcher = Some(watcher::Watcher::start(
                    self.shared.clone(),
                    self.emit.clone(),
                    engine.sender(),
                ));
                inner.engine = Some(engine);
            }
            inner.engine.as_ref().expect("just started").send(command);
            Ok(())
        }
        #[cfg(not(windows))]
        {
            let _ = command;
            Err("audio_unavailable")
        }
    }

    /// Sends only if the engine is running (pause/stop never start it).
    pub fn send_if_running(&self, command: Command) {
        #[cfg(windows)]
        if let Ok(inner) = self.inner.lock() {
            if let Some(engine) = inner.engine.as_ref() {
                engine.send(command);
            }
        }
        #[cfg(not(windows))]
        let _ = command;
    }

    /// Sets the volume (0..=1); kept for when the engine starts.
    pub fn set_volume(&self, volume: f32) {
        #[cfg(windows)]
        {
            if let Ok(mut inner) = self.inner.lock() {
                inner.volume = volume;
                if let Some(engine) = inner.engine.as_ref() {
                    engine.send(Command::SetVolume(volume));
                }
            }
        }
        #[cfg(not(windows))]
        let _ = volume;
    }

    /// Applies a new preference to the running engine.
    pub fn set_preference(&self, preference: AudioPreference) {
        let devices = match self.shared.lock() {
            Ok(mut shared) => {
                shared.preference = preference.clone();
                shared.devices.clone()
            }
            Err(_) => return,
        };
        let device = effective_device(&preference, &devices);
        self.send_if_running(Command::SetSettings(engine_settings(&preference, device)));
    }

    /// Stops playback and releases the device (window close, app exit).
    pub fn shutdown(&self) {
        #[cfg(windows)]
        if let Ok(mut inner) = self.inner.lock() {
            inner.watcher = None;
            inner.engine = None; // dropping joins the engine threads
        }
    }

    #[cfg(windows)]
    fn start_engine(&self, volume: f32) -> Result<super::engine::AudioEngine, &'static str> {
        use super::engine::{AudioEngine, WasapiPlatform};
        let devices = super::output::list_devices().unwrap_or_default();
        let preference = {
            let mut shared = self.shared.lock().map_err(|_| "audio_unavailable")?;
            shared.devices = devices.clone();
            shared.preference.clone()
        };
        let settings = engine_settings(&preference, effective_device(&preference, &devices));
        let emit = self.emit.clone();
        let root = self.root.clone();
        let shared = self.shared.clone();
        AudioEngine::spawn(Arc::new(WasapiPlatform), settings, volume, move |event| {
            let device = match &event {
                Event::SignalPath { .. } => current_device(&shared),
                _ => None,
            };
            let root = root().unwrap_or_default();
            let mut payload = event_payload(&event, &root, device.as_ref());
            if let Event::SignalPath { negotiated, .. } = &event {
                // Strict exclusive: the slider is disabled (use the DAC/amp).
                let allow = shared
                    .lock()
                    .map(|shared| shared.preference.exclusive_volume)
                    .unwrap_or(false);
                payload["volumeLocked"] = json!(negotiated.mode == OutputMode::Exclusive && !allow);
            }
            emit(payload);
        })
        .map_err(|_| "audio_unavailable")
    }
}

/// The device the engine is using now (saved choice if connected, else the
/// Windows default), refreshed from the system.
#[cfg(windows)]
fn current_device(shared: &Arc<Mutex<Shared>>) -> Option<DeviceInfo> {
    let devices = super::output::list_devices().ok()?;
    let mut shared = shared.lock().ok()?;
    shared.devices = devices.clone();
    let wanted = effective_device(&shared.preference, &devices);
    devices.into_iter().find(|device| match &wanted {
        Some(id) => &device.id == id,
        None => device.is_default,
    })
}

#[cfg(windows)]
mod watcher {
    //! Windows endpoint notifications (devices added, removed, state or
    //! default changed). Debounced; emits `deviceChanged` with the new list,
    //! moves playback to the default output when the chosen device goes
    //! away (the engine stops with `audio_device_lost` if it was playing),
    //! and back when it returns.

    use std::sync::mpsc::{self, RecvTimeoutError, Sender};
    use std::sync::{Arc, Mutex};
    use std::thread::JoinHandle;
    use std::time::Duration;

    use serde_json::json;
    use wasapi::{DeviceEnumerator, DeviceEventCallbacks, Direction, Role};

    use super::{device_json, effective_device, engine_settings, Emit, Shared};
    use crate::audio::engine::{Command, EngineSender};

    const DEBOUNCE: Duration = Duration::from_millis(300);

    enum Signal {
        Changed { default: bool },
        Stop,
    }

    pub struct Watcher {
        signals: Sender<Signal>,
        thread: Option<JoinHandle<()>>,
    }

    impl Watcher {
        pub fn start(shared: Arc<Mutex<Shared>>, emit: Emit, engine: EngineSender) -> Self {
            let (signals, inbox) = mpsc::channel();
            let callbacks_tx = signals.clone();
            let thread = std::thread::Builder::new()
                .name("qtmedia-audio-devices".into())
                .spawn(move || {
                    let _ = wasapi::initialize_mta();
                    let Ok(enumerator) = DeviceEnumerator::new() else {
                        return;
                    };
                    let mut callbacks = DeviceEventCallbacks::new();
                    let changed = move |tx: &Sender<Signal>, default: bool| {
                        let _ = tx.send(Signal::Changed { default });
                    };
                    let (a, b, c, d) = (
                        callbacks_tx.clone(),
                        callbacks_tx.clone(),
                        callbacks_tx.clone(),
                        callbacks_tx,
                    );
                    callbacks.set_device_state_callback(move |_, _| changed(&a, false));
                    callbacks.set_device_added_callback(move |_| changed(&b, false));
                    callbacks.set_device_removed_callback(move |_| changed(&c, false));
                    callbacks.set_default_device_callback(move |direction, role, _| {
                        if matches!(direction, Direction::Render) && matches!(role, Role::Console) {
                            changed(&d, true);
                        }
                    });
                    let Ok(_registration) = enumerator.register_notification_callback(callbacks)
                    else {
                        return;
                    };
                    while let Ok(Signal::Changed { default }) = inbox.recv() {
                        let mut default_changed = default;
                        loop {
                            match inbox.recv_timeout(DEBOUNCE) {
                                Ok(Signal::Changed { default }) => default_changed |= default,
                                Ok(Signal::Stop) | Err(RecvTimeoutError::Disconnected) => return,
                                Err(RecvTimeoutError::Timeout) => break,
                            }
                        }
                        refresh(&shared, &emit, &engine, default_changed);
                    }
                })
                .ok();
            Self { signals, thread }
        }
    }

    impl Drop for Watcher {
        fn drop(&mut self) {
            let _ = self.signals.send(Signal::Stop);
            if let Some(thread) = self.thread.take() {
                let _ = thread.join();
            }
        }
    }

    fn refresh(
        shared: &Arc<Mutex<Shared>>,
        emit: &Emit,
        engine: &EngineSender,
        default_changed: bool,
    ) {
        let Ok(devices) = crate::audio::output::list_devices() else {
            return;
        };
        let Ok(mut state) = shared.lock() else {
            return;
        };
        let before = effective_device(&state.preference, &state.devices);
        let after = effective_device(&state.preference, &devices);
        let preference = state.preference.clone();
        state.devices = devices.clone();
        drop(state);
        emit(json!({
            "type": "deviceChanged",
            "devices": devices.iter().map(device_json).collect::<Vec<_>>(),
            // The chosen device is gone: playing on the Windows default.
            "fallback": preference.device_id.is_some() && after.is_none(),
        }));
        if before != after {
            engine.send(Command::SetSettings(engine_settings(&preference, after)));
        } else if default_changed && after.is_none() {
            engine.send(Command::DefaultDeviceChanged);
        }
    }
}
