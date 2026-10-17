use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};

use qtmedia_app::durations::{measure, DurationCache, Item};

fn item(path: &str, size: u64) -> Item {
    Item {
        relative_path: path.to_owned(),
        size_bytes: size,
        modified_at: 1.5,
    }
}

#[test]
fn files_are_measured_once_and_remembered_across_launches() {
    let state = tempfile::tempdir().unwrap();
    let cache_file = state.path().join("durations.json");
    let root = PathBuf::from("C:/Library");
    let calls = AtomicUsize::new(0);
    let measure = |item: &Item| {
        calls.fetch_add(1, Ordering::SeqCst);
        (item.relative_path != "video/broken.mp4").then_some(42.0)
    };
    let items = vec![
        item("audio/a.flac", 10),
        item("video/b.mp4", 20),
        item("video/broken.mp4", 30),
    ];

    let cache = DurationCache::new(cache_file.clone());
    assert_eq!(
        cache.durations(&root, &items, measure),
        vec![Some(42.0), Some(42.0), None]
    );
    assert_eq!(calls.load(Ordering::SeqCst), 3);
    // A second listing, and a fresh cache reading the saved file, measure nothing.
    cache.durations(&root, &items, measure);
    DurationCache::new(cache_file).durations(&root, &items, measure);
    assert_eq!(calls.load(Ordering::SeqCst), 3);
}

#[test]
fn a_changed_file_is_measured_again_and_gone_files_are_forgotten() {
    let state = tempfile::tempdir().unwrap();
    let cache_file = state.path().join("durations.json");
    let root = PathBuf::from("C:/Library");
    let cache = DurationCache::new(cache_file.clone());
    cache.durations(
        &root,
        &[item("audio/a.flac", 10), item("audio/b.flac", 10)],
        |_| Some(1.0),
    );

    let calls = AtomicUsize::new(0);
    let durations = cache.durations(&root, &[item("audio/a.flac", 11)], |_| {
        calls.fetch_add(1, Ordering::SeqCst);
        Some(2.0)
    });

    assert_eq!(durations, vec![Some(2.0)]);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let saved = fs::read_to_string(cache_file).unwrap();
    assert!(!saved.contains("b.flac"));
}

#[test]
fn songs_are_measured_by_the_decoder() {
    let dir = tempfile::tempdir().unwrap();
    fs::create_dir_all(dir.path().join("audio")).unwrap();
    let fixture =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/audio/tagged.flac");
    fs::copy(fixture, dir.path().join("audio/Song.flac")).unwrap();

    let seconds = measure(dir.path(), "audio/Song.flac", None).unwrap();

    assert!(seconds > 0.0);
    // Without ffprobe a video cannot be measured, and paths stay confined.
    assert_eq!(measure(dir.path(), "video/missing.mp4", None), None);
    assert_eq!(measure(dir.path(), "../outside.flac", None), None);
}
