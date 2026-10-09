use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

const PREFERENCE_VERSION: u8 = 1;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SettingsError {
    InvalidPreference,
    StorageUnavailable,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LibraryPreference {
    version: u8,
    custom_root: Option<PathBuf>,
}

impl Default for LibraryPreference {
    fn default() -> Self {
        Self {
            version: PREFERENCE_VERSION,
            custom_root: None,
        }
    }
}

impl LibraryPreference {
    pub fn custom(root: PathBuf) -> Self {
        Self {
            version: PREFERENCE_VERSION,
            custom_root: Some(root),
        }
    }
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
    let temporary = preference_path.with_extension("json.tmp");
    let bytes = serde_json::to_vec(preference).map_err(|_| SettingsError::InvalidPreference)?;
    fs::write(&temporary, bytes).map_err(|_| SettingsError::StorageUnavailable)?;
    if preference_path.exists() {
        fs::remove_file(preference_path).map_err(|_| SettingsError::StorageUnavailable)?;
    }
    fs::rename(&temporary, preference_path).map_err(|_| SettingsError::StorageUnavailable)
}
