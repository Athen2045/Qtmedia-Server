//! Device outputs for the native engine.
//!
//! An [`Output`] takes device-format bytes (from `convert::Converter`) in
//! whole frames. The render thread drives it: `wait` for space, `write` up to
//! that many frames. WASAPI objects are COM pointers and are not `Send`, so
//! the render thread opens its own output.

pub mod fake;

#[cfg(windows)]
mod device;
#[cfg(windows)]
mod exclusive;
#[cfg(windows)]
mod shared;

#[cfg(windows)]
pub use device::{list_devices, WasapiCaps};
#[cfg(windows)]
pub use exclusive::WasapiExclusive;
#[cfg(windows)]
pub use shared::WasapiShared;

use std::collections::VecDeque;

#[cfg(windows)]
use super::format::{DeviceCaps, Negotiated, OutputMode};
use super::format::{PcmFormat, Reason};

pub trait Output {
    fn format(&self) -> PcmFormat;
    /// Frames the device can take now. Before `start` this returns at once
    /// (prefill); afterwards it waits for the device event, returning 0 on
    /// timeout. Exclusive outputs always report their whole buffer.
    fn wait(&mut self, timeout_ms: u32) -> Result<usize, OutputError>;
    /// Writes whole frames, at most the last `wait` result. Exclusive outputs
    /// pad a short write with silence (WASAPI rejects partial buffers).
    /// Returns the real frames written.
    fn write(&mut self, bytes: &[u8]) -> Result<usize, OutputError>;
    fn start(&mut self) -> Result<(), OutputError>;
    /// Stops the stream, keeping buffered audio (resume with `start`).
    fn pause(&mut self) -> Result<(), OutputError>;
    /// Stops and discards buffered audio (seek); the position restarts at 0.
    fn flush(&mut self) -> Result<(), OutputError>;
    /// Real (non-padding) frames the device has played since open or flush.
    fn position_frames(&mut self) -> Result<u64, OutputError>;
}

/// Stable error codes shared with the UI.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputError {
    Busy,
    ExclusiveDenied,
    FormatUnsupported,
    DeviceLost,
    Unavailable,
    /// The output is a headset's Hands-Free endpoint and it has no stereo one.
    HandsFreeOnly,
}

impl OutputError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Busy => "audio_device_busy",
            Self::ExclusiveDenied => "audio_exclusive_denied",
            Self::FormatUnsupported => "audio_format_unsupported",
            Self::DeviceLost => "audio_device_lost",
            Self::Unavailable => "audio_unavailable",
            Self::HandsFreeOnly => "audio_hands_free_only",
        }
    }
}

impl std::fmt::Display for OutputError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for OutputError {}

pub const AUDCLNT_E_DEVICE_INVALIDATED: u32 = 0x8889_0004;
pub const AUDCLNT_E_UNSUPPORTED_FORMAT: u32 = 0x8889_0008;
pub const AUDCLNT_E_DEVICE_IN_USE: u32 = 0x8889_000A;
pub const AUDCLNT_E_EXCLUSIVE_MODE_NOT_ALLOWED: u32 = 0x8889_000E;
pub const AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED: u32 = 0x8889_0019;
pub const AUDCLNT_E_RESOURCES_INVALIDATED: u32 = 0x8889_0026;
pub const E_NOTFOUND: u32 = 0x8007_0490;

/// Maps a WASAPI HRESULT to a stable error.
pub fn map_hresult(code: u32) -> OutputError {
    match code {
        AUDCLNT_E_DEVICE_IN_USE => OutputError::Busy,
        AUDCLNT_E_EXCLUSIVE_MODE_NOT_ALLOWED => OutputError::ExclusiveDenied,
        AUDCLNT_E_UNSUPPORTED_FORMAT => OutputError::FormatUnsupported,
        AUDCLNT_E_DEVICE_INVALIDATED | AUDCLNT_E_RESOURCES_INVALIDATED | E_NOTFOUND => {
            OutputError::DeviceLost
        }
        _ => OutputError::Unavailable,
    }
}

/// Whether a failed exclusive open should fall back to shared mode, and why.
/// Some drivers (Intel Smart Sound for Bluetooth) accept every format in
/// `IsFormatSupported` and then refuse it in `Initialize`.
pub fn exclusive_fallback(error: OutputError) -> Option<Reason> {
    match error {
        OutputError::FormatUnsupported => Some(Reason::FormatUnsupported),
        OutputError::ExclusiveDenied => Some(Reason::ExclusiveDenied),
        _ => None,
    }
}

/// Opens the negotiated output, falling back to shared mode when the device
/// refuses exclusive mode at open time. Returns the path actually used.
#[cfg(windows)]
pub fn open_output(
    caps: &WasapiCaps,
    negotiated: Negotiated,
    volume: f32,
) -> Result<(Box<dyn Output>, Negotiated), OutputError> {
    let mut negotiated = negotiated;
    if negotiated.mode == OutputMode::Exclusive {
        match WasapiExclusive::open(Some(caps.id()), negotiated.output) {
            Ok(output) => return Ok((Box::new(output), negotiated)),
            Err(error) => match exclusive_fallback(error) {
                Some(reason) => negotiated = Negotiated::shared(caps.mix_format(), volume, reason),
                None => return Err(error),
            },
        }
    }
    let output = WasapiShared::open(Some(caps.id()))?;
    negotiated.output = output.format();
    Ok((Box::new(output), negotiated))
}

/// How an endpoint reaches the listener.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Transport {
    Wired,
    /// A2DP / LE Audio: re-encoded by a lossy codec, never bit-perfect.
    Bluetooth,
    /// Hands-free / headset call profile: mono, telephone quality.
    BluetoothHandsFree,
}

/// Classifies an endpoint from its device instance path (Bluetooth paths
/// start with `BTHENUM\` or `BTHLE`, followed by the profile's service UUID)
/// and its adapter name.
pub fn classify_transport(instance_path: &str, adapter_name: &str) -> Transport {
    let path = instance_path.to_ascii_uppercase();
    let bluetooth = path.contains("BTHENUM") || path.contains("BTHLE");
    if !bluetooth && !adapter_name.to_ascii_lowercase().contains("bluetooth") {
        return Transport::Wired;
    }
    // Hands-Free (0x111E), Hands-Free AG (0x111F), Headset (0x1108), Headset AG (0x1112).
    const CALL_PROFILES: [&str; 4] = ["{0000111E-", "{0000111F-", "{00001108-", "{00001112-"];
    if CALL_PROFILES.iter().any(|uuid| path.contains(uuid)) {
        Transport::BluetoothHandsFree
    } else {
        Transport::Bluetooth
    }
}

/// Classifies an endpoint from both places Windows records a Bluetooth path:
/// Windows' own A2DP / Hands-Free drivers make the endpoint's device path
/// `BTHENUM\…`; offloading drivers (e.g. Intel Smart Sound) keep their own
/// device path and record the headset in a separate Bluetooth path.
pub fn endpoint_transport(
    bluetooth_path: &str,
    device_path: &str,
    adapter_name: &str,
) -> Transport {
    [bluetooth_path, device_path]
        .iter()
        .map(|path| classify_transport(path, adapter_name))
        .find(|transport| *transport != Transport::Wired)
        .unwrap_or(Transport::Wired)
}

/// A render endpoint as the hands-free lockout sees it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Endpoint {
    pub id: String,
    pub transport: Transport,
    /// Windows' container id: every endpoint of one physical headset shares it.
    pub container: Option<String>,
}

/// The endpoint to open for `chosen`. Opening a Hands-Free endpoint for
/// playback switches the headset into its mono call profile, so it is never
/// used: the same headset's stereo (A2DP) endpoint plays instead. `None` when
/// the headset has no stereo endpoint.
pub fn avoid_hands_free(chosen: &str, endpoints: &[Endpoint]) -> Option<String> {
    let Some(picked) = endpoints.iter().find(|endpoint| endpoint.id == chosen) else {
        return Some(chosen.to_owned());
    };
    if picked.transport != Transport::BluetoothHandsFree {
        return Some(chosen.to_owned());
    }
    let container = picked.container.as_deref()?;
    endpoints
        .iter()
        .find(|endpoint| {
            endpoint.transport == Transport::Bluetooth
                && endpoint.container.as_deref() == Some(container)
        })
        .map(|endpoint| endpoint.id.clone())
}

/// An output endpoint for the device picker.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeviceInfo {
    pub id: String,
    pub name: String,
    pub transport: Transport,
    pub is_default: bool,
}

/// Turns the device's played-frame count into real frames, skipping the
/// silence written to pad exclusive buffers.
#[derive(Debug, Default)]
pub struct PositionTracker {
    written: u64,
    real: u64,
    /// Silence spans (start, length) in device frames, oldest first.
    silence: VecDeque<(u64, u64)>,
    silence_played: u64,
}

impl PositionTracker {
    /// Records one write: `real` frames followed by `silence` padding frames.
    pub fn wrote(&mut self, real: u64, silence: u64) {
        self.written += real;
        self.real += real;
        if silence > 0 {
            self.silence.push_back((self.written, silence));
            self.written += silence;
        }
    }

    pub fn written(&self) -> u64 {
        self.written
    }

    /// Real frames played once the device has played `played` frames.
    pub fn real_played(&mut self, played: u64) -> u64 {
        let played = played.min(self.written);
        while let Some(&(start, len)) = self.silence.front() {
            if start + len > played {
                break;
            }
            self.silence_played += len;
            self.silence.pop_front();
        }
        let partial = self
            .silence
            .front()
            .map_or(0, |&(start, _)| played.saturating_sub(start));
        (played - self.silence_played - partial).min(self.real)
    }

    pub fn reset(&mut self) {
        *self = Self::default();
    }
}
