use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

const PREFERENCE_VERSION: u8 = 1;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SettingsError {
    InvalidPreference,
    StorageUnavailable,
}

const PROXY_SCHEMES: &[&str] = &["http", "https", "socks4", "socks4a", "socks5", "socks5h"];
const MAX_PROXY_LENGTH: usize = 2048;

/// DNS-over-HTTPS resolvers, addressed by IP so they work when system DNS lies.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DohProvider {
    #[default]
    Off,
    Cloudflare,
    Google,
    Quad9,
}

impl DohProvider {
    pub fn url(self) -> Option<&'static str> {
        match self {
            Self::Off => None,
            Self::Cloudflare => Some("https://1.1.1.1/dns-query"),
            Self::Google => Some("https://8.8.8.8/dns-query"),
            Self::Quad9 => Some("https://9.9.9.9/dns-query"),
        }
    }
}

/// Browser whose cookies the engine may reuse for sites behind a Cloudflare
/// challenge (see `desktop_service/browser_cookies.py`). Only Firefox: Chrome
/// and Edge encrypt cookies on Windows so other programs cannot read them.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CookieSource {
    #[default]
    Off,
    Firefox,
}

impl CookieSource {
    pub fn browser(self) -> Option<&'static str> {
        match self {
            Self::Off => None,
            Self::Firefox => Some("firefox"),
        }
    }
}

/// How the media engine reaches sources. Stored locally; never logged.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkPreference {
    #[serde(default)]
    pub doh: DohProvider,
    #[serde(default)]
    pub proxy: Option<String>,
    #[serde(default)]
    pub cookies: CookieSource,
}

/// Accept `scheme://[user:pass@]host:port` for the proxies yt-dlp and curl
/// support. An empty value means no proxy.
pub fn validate_proxy(value: &str) -> Result<Option<String>, SettingsError> {
    let value = value.trim();
    if value.is_empty() {
        return Ok(None);
    }
    if value.len() > MAX_PROXY_LENGTH || value.chars().any(|c| c.is_whitespace() || c.is_control())
    {
        return Err(SettingsError::InvalidPreference);
    }
    let parsed = url::Url::parse(value).map_err(|_| SettingsError::InvalidPreference)?;
    let valid = PROXY_SCHEMES.contains(&parsed.scheme())
        && parsed.host_str().is_some_and(|host| !host.is_empty())
        && parsed.port().is_some();
    valid
        .then(|| Some(value.to_owned()))
        .ok_or(SettingsError::InvalidPreference)
}

/// Native audio engine output choice (`preferences.json` → `audio`).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AudioMode {
    #[default]
    Shared,
    Exclusive,
}

/// What exclusive mode does when the device cannot take the file's rate.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RateMismatchPreference {
    /// Fall back to shared mode and say why.
    #[default]
    Strict,
    /// Stay exclusive at a supported rate (not bit-perfect).
    Resample,
}

const MAX_DEVICE_ID_LENGTH: usize = 512;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AudioPreference {
    /// Endpoint ID; `None` follows the Windows default output.
    #[serde(default)]
    pub device_id: Option<String>,
    #[serde(default)]
    pub mode: AudioMode,
    #[serde(default)]
    pub rate_mismatch: RateMismatchPreference,
    /// Software volume in exclusive mode (drops bit-perfect below 100 %).
    #[serde(default)]
    pub exclusive_volume: bool,
    /// Play songs at one loudness. On by default (older files load as on).
    #[serde(default = "levelling_default")]
    pub levelling: bool,
}

fn levelling_default() -> bool {
    true
}

impl Default for AudioPreference {
    fn default() -> Self {
        Self {
            device_id: None,
            mode: AudioMode::default(),
            rate_mismatch: RateMismatchPreference::default(),
            exclusive_volume: false,
            levelling: true,
        }
    }
}

/// Rejects device IDs that are not plausible Windows endpoint IDs.
pub fn validate_audio(preference: AudioPreference) -> Result<AudioPreference, SettingsError> {
    let device_id = match preference.device_id {
        Some(id) if id.trim().is_empty() => None,
        Some(id)
            if id.len() > MAX_DEVICE_ID_LENGTH
                || id.chars().any(|c| c.is_control() || c.is_whitespace()) =>
        {
            return Err(SettingsError::InvalidPreference)
        }
        other => other,
    };
    Ok(AudioPreference {
        device_id,
        ..preference
    })
}

/// The saved audio choice; anything unreadable or invalid falls back to
/// shared mode on the default device.
pub fn load_audio(preference_path: &Path) -> AudioPreference {
    fs::read(preference_path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<LibraryPreference>(&bytes).ok())
        .and_then(|preference| preference.audio)
        .and_then(|audio| validate_audio(audio).ok())
        .unwrap_or_default()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LibraryPreference {
    version: u8,
    custom_root: Option<PathBuf>,
    #[serde(default)]
    network: NetworkPreference,
    /// `None` when saving keeps whatever audio choice the file already has,
    /// so library and network changes never reset it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    audio: Option<AudioPreference>,
}

impl Default for LibraryPreference {
    fn default() -> Self {
        Self {
            version: PREFERENCE_VERSION,
            custom_root: None,
            network: NetworkPreference::default(),
            audio: None,
        }
    }
}

impl LibraryPreference {
    pub fn custom(root: PathBuf) -> Self {
        Self {
            custom_root: Some(root),
            ..Self::default()
        }
    }

    pub fn with_network(mut self, network: NetworkPreference) -> Self {
        self.network = network;
        self
    }

    pub fn network(&self) -> &NetworkPreference {
        &self.network
    }

    pub fn with_audio(mut self, audio: AudioPreference) -> Self {
        self.audio = Some(audio);
        self
    }
}

/// The saved network choice; anything unreadable or invalid falls back to off.
pub fn load_network(preference_path: &Path) -> NetworkPreference {
    let Some(preference) = fs::read(preference_path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<LibraryPreference>(&bytes).ok())
    else {
        return NetworkPreference::default();
    };
    let mut network = preference.network;
    network.proxy = network
        .proxy
        .as_deref()
        .and_then(|proxy| validate_proxy(proxy).ok().flatten());
    network
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LibraryLocation {
    #[serde(skip)]
    pub root: PathBuf,
    pub path: String,
    pub is_default: bool,
}

impl LibraryLocation {
    pub fn new(root: PathBuf, is_default: bool) -> Self {
        let path = root.to_string_lossy().into_owned();
        Self {
            root,
            path,
            is_default,
        }
    }
}

pub fn load_preference(
    preference_path: &Path,
    default_root: &Path,
) -> Result<LibraryLocation, SettingsError> {
    if !preference_path.exists() {
        return Ok(LibraryLocation::new(default_root.to_path_buf(), true));
    }
    let bytes = fs::read(preference_path).map_err(|_| SettingsError::StorageUnavailable)?;
    let preference: LibraryPreference =
        serde_json::from_slice(&bytes).map_err(|_| SettingsError::InvalidPreference)?;
    if preference.version != PREFERENCE_VERSION {
        return Err(SettingsError::InvalidPreference);
    }
    Ok(match preference.custom_root {
        Some(root) => {
            let validated = crate::paths::selected_library_root(&root)
                .map_err(|_| SettingsError::InvalidPreference)?;
            if validated != root {
                return Err(SettingsError::InvalidPreference);
            }
            LibraryLocation::new(root, false)
        }
        None => LibraryLocation::new(default_root.to_path_buf(), true),
    })
}

pub fn save_preference(
    preference_path: &Path,
    preference: &LibraryPreference,
) -> Result<(), SettingsError> {
    let parent = preference_path
        .parent()
        .ok_or(SettingsError::StorageUnavailable)?;
    fs::create_dir_all(parent).map_err(|_| SettingsError::StorageUnavailable)?;
    let mut preference = preference.clone();
    if preference.audio.is_none() {
        preference.audio = fs::read(preference_path)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<LibraryPreference>(&bytes).ok())
            .and_then(|existing| existing.audio);
    }
    let temporary = preference_path.with_extension("json.tmp");
    let bytes = serde_json::to_vec(&preference).map_err(|_| SettingsError::InvalidPreference)?;
    fs::write(&temporary, bytes).map_err(|_| SettingsError::StorageUnavailable)?;
    if preference_path.exists() {
        fs::remove_file(preference_path).map_err(|_| SettingsError::StorageUnavailable)?;
    }
    fs::rename(&temporary, preference_path).map_err(|_| SettingsError::StorageUnavailable)
}

/// Stores the audio choice, keeping the library location and network
/// settings already in the file. A file that exists but cannot be read is
/// left alone (never replaced with defaults).
pub fn save_audio(preference_path: &Path, audio: AudioPreference) -> Result<(), SettingsError> {
    let existing = match fs::read(preference_path) {
        Ok(bytes) => serde_json::from_slice::<LibraryPreference>(&bytes)
            .map_err(|_| SettingsError::InvalidPreference)?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => LibraryPreference::default(),
        Err(_) => return Err(SettingsError::StorageUnavailable),
    };
    save_preference(
        preference_path,
        &existing.with_audio(validate_audio(audio)?),
    )
}
