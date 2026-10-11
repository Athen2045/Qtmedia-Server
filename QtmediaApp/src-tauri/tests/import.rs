//! Files → Import: routing by type, never overwriting, skipping the rest.

use std::fs;
use std::path::PathBuf;

use qtmedia_app::import::{copy_file, folder_for, free_name, import_files};

#[test]
fn files_go_to_audio_or_video_by_type() {
    assert_eq!(folder_for("a/Song.FLAC".as_ref()), Some("audio"));
    assert_eq!(folder_for("Song.mp3".as_ref()), Some("audio"));
    for video in [
        "Film.mkv",
        "Clip.MOV",
        "Talk.webm",
        "Show.m4v",
        "Old.avi",
        "x.mp4",
    ] {
        assert_eq!(folder_for(video.as_ref()), Some("video"), "{video}");
    }
    for other in ["Song.wav", "notes.txt", "setup.exe", "noextension"] {
        assert_eq!(folder_for(other.as_ref()), None, "{other}");
    }
}

#[test]
fn imports_copies_and_never_overwrites() {
    let source = tempfile::tempdir().unwrap();
    let library = tempfile::tempdir().unwrap();
    fs::create_dir_all(library.path().join("video")).unwrap();
    fs::write(library.path().join("video/Film.mkv"), b"existing").unwrap();
    let files: Vec<PathBuf> = ["Film.mkv", "Song.flac", "readme.txt", "missing.mp3"]
        .iter()
        .map(|name| source.path().join(name))
        .collect();
    fs::write(&files[0], b"new film").unwrap();
    fs::write(&files[1], b"song").unwrap();
    fs::write(&files[2], b"text").unwrap();

    let report = import_files(library.path(), &files, copy_file);

    assert_eq!(report.imported, ["video/Film (2).mkv", "audio/Song.flac"]);
    assert_eq!(report.skipped, 2);
    assert_eq!(
        fs::read(library.path().join("video/Film.mkv")).unwrap(),
        b"existing"
    );
    assert_eq!(
        fs::read(library.path().join("video/Film (2).mkv")).unwrap(),
        b"new film"
    );
    assert!(files[0].exists(), "the source is kept");
    let leftovers: Vec<_> = fs::read_dir(library.path().join("video"))
        .unwrap()
        .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|name| name.ends_with(".part"))
        .collect();
    assert!(leftovers.is_empty(), "{leftovers:?}");
}

#[test]
fn a_failed_copy_is_skipped_and_cleaned_up() {
    let source = tempfile::tempdir().unwrap();
    let library = tempfile::tempdir().unwrap();
    let file = source.path().join("Clip.mov");
    fs::write(&file, b"x").unwrap();
    let report = import_files(library.path(), &[file], |_, to| {
        fs::write(to, b"half").unwrap();
        false
    });
    assert!(report.imported.is_empty());
    assert_eq!(report.skipped, 1);
    assert_eq!(
        fs::read_dir(library.path().join("video")).unwrap().count(),
        0
    );
}

#[test]
fn free_names_count_up() {
    let dir = tempfile::tempdir().unwrap();
    assert_eq!(free_name(dir.path(), "A.mp3"), dir.path().join("A.mp3"));
    fs::write(dir.path().join("A.mp3"), b"").unwrap();
    fs::write(dir.path().join("A (2).mp3"), b"").unwrap();
    assert_eq!(free_name(dir.path(), "A.mp3"), dir.path().join("A (3).mp3"));
}
