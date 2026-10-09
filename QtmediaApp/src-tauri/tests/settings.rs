use std::path::Path;

use qtmedia_app::paths::{selected_library_root, PathError};
use qtmedia_app::settings::{load_preference, save_preference, LibraryPreference};

#[test]
fn first_run_uses_default_library_without_creating_a_preference() {
    let temp = tempfile::tempdir().unwrap();
    let preference = temp.path().join("preferences.json");
    let default_root = temp.path().join("app-data").join("Qtmedia").join("library");

    let loaded = load_preference(&preference, &default_root).unwrap();

    assert_eq!(loaded.root, default_root);
    assert!(loaded.is_default);
    assert!(!preference.exists());
}

#[test]
fn custom_library_preference_survives_a_reload() {
    let temp = tempfile::tempdir().unwrap();
    let preference = temp.path().join("preferences.json");
    let default_root = temp.path().join("default").join("Qtmedia").join("library");
    let custom_root = temp.path().join("Media").join("Qtmedia").join("library");

    save_preference(&preference, &LibraryPreference::custom(custom_root.clone())).unwrap();
    let loaded = load_preference(&preference, &default_root).unwrap();

    assert_eq!(loaded.root, custom_root);
    assert!(!loaded.is_default);
}

#[test]
fn selected_parent_gets_an_application_owned_library() {
    let selected = Path::new("media-parent");
    assert_eq!(
        selected_library_root(selected).unwrap(),
        selected.join("Qtmedia").join("library")
    );
}

#[test]
fn selecting_an_existing_qtmedia_library_does_not_nest_it() {
    let selected = Path::new("media-parent").join("Qtmedia").join("library");
    assert_eq!(selected_library_root(&selected).unwrap(), selected);
}

#[test]
fn filesystem_root_is_not_a_valid_download_location() {
    let root = if cfg!(windows) {
        Path::new(r"C:\")
    } else {
        Path::new("/")
    };
    assert_eq!(selected_library_root(root), Err(PathError::UnsafePath));
}

#[test]
fn preference_write_replaces_existing_value_without_leaving_a_temp_file() {
    let temp = tempfile::tempdir().unwrap();
    let preference = temp.path().join("preferences.json");
    save_preference(
        &preference,
        &LibraryPreference::custom(Path::new("first").to_path_buf()),
    )
    .unwrap();
    save_preference(&preference, &LibraryPreference::default()).unwrap();

    let loaded = load_preference(&preference, Path::new("default-root")).unwrap();
    assert!(loaded.is_default);
    assert_eq!(loaded.root, Path::new("default-root"));
    assert!(!preference.with_extension("json.tmp").exists());
}

#[test]
fn tampered_preference_cannot_turn_a_filesystem_root_into_the_library() {
    let temp = tempfile::tempdir().unwrap();
    let preference = temp.path().join("preferences.json");
    let filesystem_root = if cfg!(windows) {
        Path::new(r"C:\")
    } else {
        Path::new("/")
    };
    save_preference(
        &preference,
        &LibraryPreference::custom(filesystem_root.to_path_buf()),
    )
    .unwrap();

    assert!(load_preference(&preference, &temp.path().join("default")).is_err());
}
