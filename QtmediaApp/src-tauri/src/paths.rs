use std::fs;
use std::path::{Component, Path, PathBuf};

use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PathError {
    UnsafePath,
    NotFound,
    StorageUnavailable,
}

pub fn prepare_library(root: &Path) -> Result<(), PathError> {
    for directory in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(root.join(directory)).map_err(|_| PathError::StorageUnavailable)?;
    }
    Ok(())
}

pub fn selected_library_root(selection: &Path) -> Result<PathBuf, PathError> {
    if selection.as_os_str().is_empty() || selection.parent().is_none() {
        return Err(PathError::UnsafePath);
    }
    let is_existing_layout = selection
        .file_name()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case("library"))
        && selection
            .parent()
            .and_then(Path::file_name)
            .and_then(|value| value.to_str())
            .is_some_and(|value| value.eq_ignore_ascii_case("Qtmedia"));
    Ok(if is_existing_layout {
        selection.to_path_buf()
    } else {
        selection.join("Qtmedia").join("library")
    })
}

pub fn resolve_library_entry(root: &Path, relative_path: &str) -> Result<PathBuf, PathError> {
    resolve_typed_entry(
        root,
        relative_path,
        &[
            (&["audio"][..], &["mp3"][..]),
            (&["video"][..], &["mp4"][..]),
        ],
    )
}

pub fn resolve_artwork_entry(root: &Path, relative_path: &str) -> Result<PathBuf, PathError> {
    resolve_typed_entry(
        root,
        relative_path,
        &[(&["artwork"][..], &["jpg", "jpeg", "png", "webp"][..])],
    )
}

fn resolve_typed_entry(
    root: &Path,
    relative_path: &str,
    allowed: &[(&[&str], &[&str])],
) -> Result<PathBuf, PathError> {
    let relative = Path::new(relative_path);
    if relative.is_absolute()
        || relative
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(PathError::UnsafePath);
    }

    let first = relative
        .components()
        .next()
        .and_then(|part| match part {
            Component::Normal(value) => value.to_str(),
            _ => None,
        })
        .ok_or(PathError::UnsafePath)?;
    let extension = relative
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
        .ok_or(PathError::UnsafePath)?;
    let allowed_type = allowed.iter().any(|(directories, extensions)| {
        directories.contains(&first) && extensions.contains(&extension.as_str())
    });
    if !allowed_type {
        return Err(PathError::UnsafePath);
    }

    let root = root
        .canonicalize()
        .map_err(|_| PathError::StorageUnavailable)?;
    let candidate = root.join(relative);
    let resolved = candidate.canonicalize().map_err(|_| PathError::NotFound)?;
    if !resolved.starts_with(&root) || !resolved.is_file() {
        return Err(PathError::UnsafePath);
    }
    Ok(resolved)
}
