use std::fs;

use qtmedia_app::lyrics::{read_local_lyrics, MAX_LRC_BYTES};

fn library() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for sub in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(dir.path().join(sub)).unwrap();
    }
    fs::write(dir.path().join("audio/Song.mp3"), b"x").unwrap();
    fs::write(
        dir.path().join("audio/Song.lrc"),
        "\u{feff}[00:01.00] Hello\n",
    )
    .unwrap();
    fs::write(dir.path().join("audio/Bare.mp3"), b"x").unwrap();
    fs::write(dir.path().join("video/Clip.mp4"), b"x").unwrap();
    fs::write(dir.path().join("video/Clip.lrc"), "[00:01.00] no").unwrap();
    dir
}

#[test]
fn reads_the_lrc_next_to_a_library_song() {
    let dir = library();
    assert_eq!(
        read_local_lyrics(dir.path(), "audio/Song.mp3").as_deref(),
        Some("[00:01.00] Hello\n")
    );
    assert_eq!(read_local_lyrics(dir.path(), "audio/Bare.mp3"), None);
}

#[test]
fn refuses_non_audio_escapes_and_oversized_files() {
    let dir = library();
    assert_eq!(read_local_lyrics(dir.path(), "video/Clip.mp4"), None);
    assert_eq!(
        read_local_lyrics(dir.path(), "audio/../video/Clip.mp4"),
        None
    );
    assert_eq!(read_local_lyrics(dir.path(), "audio/missing.mp3"), None);
    fs::write(
        dir.path().join("audio/Song.lrc"),
        vec![b'a'; MAX_LRC_BYTES as usize + 1],
    )
    .unwrap();
    assert_eq!(read_local_lyrics(dir.path(), "audio/Song.mp3"), None);
}

mod track_info_and_saving {
    use std::fs;
    use std::path::PathBuf;

    use qtmedia_app::lyrics::{read_local_lyrics, read_track_info, save_local_lyrics, TrackInfo};

    fn fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures/audio")
            .join(name)
    }

    fn library_with(files: &[(&str, &str)]) -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        for sub in ["audio", "video", "artwork", "temp"] {
            fs::create_dir_all(dir.path().join(sub)).unwrap();
        }
        for (fixture_name, relative) in files {
            fs::copy(fixture(fixture_name), dir.path().join(relative)).unwrap();
        }
        dir
    }

    #[test]
    fn reads_tags_and_duration_from_flac_and_mp3() {
        let dir = library_with(&[
            ("tagged.flac", "audio/Song.flac"),
            ("tagged.mp3", "audio/Song.mp3"),
        ]);
        for song in ["audio/Song.flac", "audio/Song.mp3"] {
            let info = read_track_info(dir.path(), song).unwrap();
            assert_eq!(info.title.as_deref(), Some("Fixture Song"), "{song}");
            assert_eq!(info.artist.as_deref(), Some("Fixture Artist"), "{song}");
            assert_eq!(info.album.as_deref(), Some("Fixture Album"), "{song}");
            let duration = info.duration_seconds.unwrap();
            assert!((duration - 0.5).abs() < 0.06, "{song}: {duration}");
        }
    }

    #[test]
    fn untagged_songs_have_only_a_duration() {
        let dir = library_with(&[("sine_16_44100.flac", "audio/Plain.flac")]);
        let info = read_track_info(dir.path(), "audio/Plain.flac").unwrap();
        assert_eq!(
            info,
            TrackInfo {
                duration_seconds: Some(0.25),
                ..TrackInfo::default()
            }
        );
    }

    #[test]
    fn track_info_is_confined_to_library_audio() {
        let dir = library_with(&[("tagged.flac", "audio/Song.flac")]);
        assert_eq!(read_track_info(dir.path(), "video/Song.flac"), None);
        assert_eq!(
            read_track_info(dir.path(), "audio/../audio/Song.flac"),
            None
        );
        assert_eq!(read_track_info(dir.path(), "audio/missing.flac"), None);
    }

    #[test]
    fn saves_found_lyrics_once_and_never_replaces_a_file() {
        let dir = library_with(&[("tagged.flac", "audio/Song.flac")]);
        assert!(save_local_lyrics(
            dir.path(),
            "audio/Song.flac",
            "[00:01.00] Found\n"
        ));
        assert_eq!(
            read_local_lyrics(dir.path(), "audio/Song.flac").as_deref(),
            Some("[00:01.00] Found\n")
        );
        assert!(!save_local_lyrics(
            dir.path(),
            "audio/Song.flac",
            "[00:01.00] Other"
        ));
        assert_eq!(
            read_local_lyrics(dir.path(), "audio/Song.flac").as_deref(),
            Some("[00:01.00] Found\n")
        );
        assert!(!dir.path().join("audio/Song.lrc.part").exists());
    }

    #[test]
    fn refuses_to_save_outside_library_audio_or_oversized_text() {
        let dir = library_with(&[("tagged.flac", "audio/Song.flac")]);
        assert!(!save_local_lyrics(dir.path(), "video/Clip.mp4", "x"));
        assert!(!save_local_lyrics(dir.path(), "audio/../Song.flac", "x"));
        assert!(!save_local_lyrics(dir.path(), "audio/missing.flac", "x"));
        assert!(!save_local_lyrics(dir.path(), "audio/Song.flac", "   "));
        let huge = "a".repeat(600 * 1024);
        assert!(!save_local_lyrics(dir.path(), "audio/Song.flac", &huge));
        assert!(!dir.path().join("audio/Song.lrc").exists());
    }
}
