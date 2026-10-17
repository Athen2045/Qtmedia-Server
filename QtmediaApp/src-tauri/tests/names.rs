use std::fs;
use std::path::Path;
use std::time::UNIX_EPOCH;

use qtmedia_app::names::{logged_renames, safe_stem, tidy_library, untagged_stem, Rename};
use qtmedia_app::playback::cache_name;

fn library() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for folder in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(dir.path().join(folder)).unwrap();
    }
    dir
}

fn write(root: &Path, relative: &str, bytes: &[u8]) {
    fs::write(root.join(relative), bytes).unwrap();
}

fn rename(from: &str, to: &str) -> Rename {
    Rename {
        from: from.to_owned(),
        to: to.to_owned(),
    }
}

#[test]
fn the_media_tag_is_removed_wherever_it_sits() {
    assert_eq!(untagged_stem("Song [media-1]").as_deref(), Some("Song"));
    assert_eq!(
        untagged_stem("Song [media-1] (2)").as_deref(),
        Some("Song (2)")
    );
    assert_eq!(untagged_stem("Song [media-]"), None);
    assert_eq!(untagged_stem("Song [media-a b]"), None);
    assert_eq!(untagged_stem("Song [live]"), None);
    assert_eq!(safe_stem("con"), "con_");
    assert_eq!(safe_stem(" ._"), "media");
}

#[test]
fn media_lyrics_and_cover_move_together_and_are_logged() {
    let dir = library();
    let root = dir.path();
    let log = root.join("state").join("renames.json");
    write(root, "audio/Song [media-3].mp3", b"mp3");
    write(root, "audio/Song [media-3].lrc", b"[00:01]hi");
    write(root, "artwork/Song [media-3].jpg", b"jpg");
    write(root, "video/Plain.mp4", b"untouched");

    let done = tidy_library(root, None, &log);

    assert!(root.join("audio/Song.mp3").is_file());
    assert!(root.join("audio/Song.lrc").is_file());
    assert!(root.join("artwork/Song.jpg").is_file());
    assert!(root.join("video/Plain.mp4").is_file());
    assert!(!root.join("audio/Song [media-3].mp3").exists());
    assert!(done.contains(&rename("audio/Song [media-3].mp3", "audio/Song.mp3")));
    assert_eq!(logged_renames(&log, root), done);
    // A second run finds nothing to do and keeps the log.
    assert!(tidy_library(root, None, &log).is_empty());
    assert_eq!(logged_renames(&log, root), done);
}

#[test]
fn a_stem_in_use_by_any_media_or_cover_gets_a_number() {
    let dir = library();
    let root = dir.path();
    let log = root.join("renames.json");
    write(root, "video/clip.mp4", b"other video");
    write(root, "artwork/Clip (2).png", b"another cover");
    write(root, "audio/Clip [media-1].mp3", b"first");
    write(root, "audio/Clip [media-9].mp3", b"second");

    tidy_library(root, None, &log);

    // Stems are compared case-insensitively, like Windows does.
    assert_eq!(fs::read(root.join("audio/Clip (3).mp3")).unwrap(), b"first");
    assert_eq!(
        fs::read(root.join("audio/Clip (4).mp3")).unwrap(),
        b"second"
    );
    assert_eq!(
        fs::read(root.join("video/clip.mp4")).unwrap(),
        b"other video"
    );
}

#[test]
fn a_prepared_playback_copy_follows_its_video() {
    let dir = library();
    let root = dir.path();
    let cache = tempfile::tempdir().unwrap();
    let log = root.join("renames.json");
    write(root, "video/Film [media-2].mkv", b"matroska");
    let metadata = fs::metadata(root.join("video/Film [media-2].mkv")).unwrap();
    let modified = metadata
        .modified()
        .unwrap()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let old = cache_name("video/Film [media-2].mkv", metadata.len(), modified);
    fs::write(cache.path().join(format!("{old}.mp4")), b"prepared").unwrap();

    tidy_library(root, Some(cache.path()), &log);

    let new = cache_name("video/Film.mkv", metadata.len(), modified);
    assert!(root.join("video/Film.mkv").is_file());
    assert_eq!(
        fs::read(cache.path().join(format!("{new}.mp4"))).unwrap(),
        b"prepared"
    );
    assert!(!cache.path().join(format!("{old}.mp4")).exists());
}

#[test]
fn renames_are_kept_per_library() {
    let first = library();
    let second = library();
    let log = first.path().join("renames.json");
    write(first.path(), "audio/A [media-1].mp3", b"a");
    write(second.path(), "audio/B [media-1].mp3", b"b");

    tidy_library(first.path(), None, &log);
    tidy_library(second.path(), None, &log);

    assert_eq!(
        logged_renames(&log, first.path()),
        vec![rename("audio/A [media-1].mp3", "audio/A.mp3")]
    );
    assert_eq!(
        logged_renames(&log, second.path()),
        vec![rename("audio/B [media-1].mp3", "audio/B.mp3")]
    );
}

#[test]
fn a_corrupt_log_does_not_stop_renaming() {
    let dir = library();
    let root = dir.path();
    let log = root.join("renames.json");
    fs::write(&log, b"{not json").unwrap();
    write(root, "audio/A [media-1].flac", b"a");

    let done = tidy_library(root, None, &log);

    assert_eq!(done, vec![rename("audio/A [media-1].flac", "audio/A.flac")]);
    assert_eq!(logged_renames(&log, root), done);
}

#[test]
fn lyrics_and_covers_without_media_are_left_alone() {
    let dir = library();
    let root = dir.path();
    let log = root.join("renames.json");
    write(root, "audio/First Light [media-a1].lrc", b"orphan lyrics");
    write(root, "artwork/Gone [media-b2].jpg", b"orphan cover");
    write(root, "audio/First Light [media-c3].flac", b"song");

    let done = tidy_library(root, None, &log);

    assert_eq!(
        done,
        vec![rename(
            "audio/First Light [media-c3].flac",
            "audio/First Light.flac"
        )]
    );
    assert!(root.join("audio/First Light [media-a1].lrc").is_file());
    assert!(root.join("artwork/Gone [media-b2].jpg").is_file());
}
