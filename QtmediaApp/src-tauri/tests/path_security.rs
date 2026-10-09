use std::fs;

use qtmedia_app::paths::{
    prepare_library, resolve_artwork_entry, resolve_library_entry, PathError,
};

#[test]
fn prepares_private_library_layout() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("Qtmedia").join("library");
    prepare_library(&root).unwrap();
    for directory in ["audio", "video", "artwork", "temp"] {
        assert!(root.join(directory).is_dir());
    }
}

#[test]
fn accepts_existing_media_below_audio_or_video() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("library");
    prepare_library(&root).unwrap();
    let media = root.join("audio").join("Track [abc].mp3");
    fs::write(&media, b"media").unwrap();
    assert_eq!(
        resolve_library_entry(&root, "audio/Track [abc].mp3").unwrap(),
        media.canonicalize().unwrap()
    );
}

#[test]
fn artwork_resolution_is_confined_to_supported_image_files() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("library");
    prepare_library(&root).unwrap();
    let artwork = root.join("artwork").join("Track [abc].jpg");
    fs::write(&artwork, b"image").unwrap();
    assert_eq!(
        resolve_artwork_entry(&root, "artwork/Track [abc].jpg").unwrap(),
        artwork.canonicalize().unwrap()
    );
    assert_eq!(
        resolve_artwork_entry(&root, "audio/Track [abc].mp3"),
        Err(PathError::UnsafePath)
    );
}

#[test]
fn rejects_absolute_traversal_temp_and_missing_paths() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("library");
    prepare_library(&root).unwrap();
    assert_eq!(
        resolve_library_entry(&root, "../secret.mp3"),
        Err(PathError::UnsafePath)
    );
    assert_eq!(
        resolve_library_entry(&root, "temp/partial.mp4"),
        Err(PathError::UnsafePath)
    );
    assert_eq!(
        resolve_library_entry(&root, "audio/missing.mp3"),
        Err(PathError::NotFound)
    );
    assert_eq!(
        resolve_library_entry(&root, temp.path().join("outside.mp3").to_str().unwrap()),
        Err(PathError::UnsafePath)
    );
    let unexpected = root.join("audio").join("notes.txt");
    fs::write(&unexpected, b"not media").unwrap();
    assert_eq!(
        resolve_library_entry(&root, "audio/notes.txt"),
        Err(PathError::UnsafePath)
    );
}

#[cfg(unix)]
#[test]
fn rejects_symlink_escape() {
    use std::os::unix::fs::symlink;
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("library");
    prepare_library(&root).unwrap();
    let outside = temp.path().join("outside.mp3");
    fs::write(&outside, b"media").unwrap();
    symlink(&outside, root.join("audio").join("escape.mp3")).unwrap();
    assert_eq!(
        resolve_library_entry(&root, "audio/escape.mp3"),
        Err(PathError::UnsafePath)
    );
}
