use std::fs;

use qtmedia_app::removal::remove_entries;

fn library() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for sub in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(dir.path().join(sub)).unwrap();
    }
    for file in [
        "audio/Song.mp3",
        "video/Clip.mp4",
        "artwork/Song.jpg",
        "artwork/Other.png",
        "temp/part.mp4",
    ] {
        fs::write(dir.path().join(file), b"x").unwrap();
    }
    fs::write(dir.path().join("outside.mp3"), b"x").unwrap();
    dir
}

#[test]
fn removes_only_confined_media_and_reports_the_rest() {
    let dir = library();
    let requested: Vec<String> = [
        "audio/Song.mp3",
        "video/Clip.mp4",
        "audio/Song.mp3", // duplicate counts once
        "artwork/Other.png",
        "temp/part.mp4",
        "audio/../outside.mp3",
        "audio/missing.mp3",
    ]
    .map(String::from)
    .to_vec();

    let report = remove_entries(dir.path(), &requested, |path| fs::remove_file(path).is_ok());

    assert_eq!(report.removed, ["audio/Song.mp3", "video/Clip.mp4"]);
    assert_eq!(report.failed, 4);
    assert!(!dir.path().join("audio/Song.mp3").exists());
    assert!(!dir.path().join("video/Clip.mp4").exists());
    // Song's cover went with it; artwork is never removable directly.
    assert!(!dir.path().join("artwork/Song.jpg").exists());
    for kept in ["artwork/Other.png", "temp/part.mp4", "outside.mp3"] {
        assert!(dir.path().join(kept).exists(), "{kept} must survive");
    }
}

#[test]
fn a_failed_removal_is_counted_not_reported_as_removed() {
    let dir = library();
    let report = remove_entries(dir.path(), &["audio/Song.mp3".to_string()], |_| false);
    assert!(report.removed.is_empty());
    assert_eq!(report.failed, 1);
    assert!(dir.path().join("audio/Song.mp3").exists());
}

#[test]
fn removing_media_also_removes_its_unshared_covers() {
    let dir = library();
    fs::write(dir.path().join("artwork/Clip.webp"), b"x").unwrap();
    fs::write(dir.path().join("artwork/Clip.png"), b"x").unwrap();
    let report = remove_entries(dir.path(), &["video/Clip.mp4".to_string()], |path| {
        fs::remove_file(path).is_ok()
    });
    assert_eq!(report.removed, ["video/Clip.mp4"]);
    assert_eq!(report.failed, 0);
    assert!(!dir.path().join("artwork/Clip.webp").exists());
    assert!(!dir.path().join("artwork/Clip.png").exists());
    assert!(
        dir.path().join("artwork/Song.jpg").exists(),
        "other covers stay"
    );
}

#[test]
fn a_cover_shared_by_another_file_with_the_same_stem_is_kept() {
    let dir = library();
    // The same song saved as MP3 and FLAC shares artwork/Song.jpg.
    fs::write(dir.path().join("audio/Song.flac"), b"x").unwrap();
    let remove = |path: &std::path::Path| fs::remove_file(path).is_ok();
    remove_entries(dir.path(), &["audio/Song.mp3".to_string()], remove);
    assert!(dir.path().join("artwork/Song.jpg").exists());

    // Removing the last file with that stem removes the cover.
    remove_entries(dir.path(), &["audio/Song.flac".to_string()], remove);
    assert!(!dir.path().join("artwork/Song.jpg").exists());
}

#[test]
fn a_cover_that_cannot_be_removed_does_not_fail_the_media_removal() {
    let dir = library();
    let report = remove_entries(dir.path(), &["audio/Song.mp3".to_string()], |path| {
        path.extension().is_some_and(|ext| ext == "mp3") && fs::remove_file(path).is_ok()
    });
    assert_eq!(report.removed, ["audio/Song.mp3"]);
    assert_eq!(report.failed, 0);
    assert!(dir.path().join("artwork/Song.jpg").exists());
}
