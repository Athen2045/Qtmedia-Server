use std::fs;
use std::path::PathBuf;

use qtmedia_app::loudness::{level_gain, measure, parse_summary, LoudnessCache, Measure};

const SUMMARY: &str = "[Parsed_ebur128_0 @ 0] Summary:\n\n  Integrated loudness:\n    I:          -8.3 LUFS\n    Threshold: -19.4 LUFS\n\n  Loudness range:\n    LRA:        18.3 LU\n\n  True peak:\n    Peak:        0.5 dBFS\n";

fn db(gain: f32) -> f64 {
    20.0 * f64::from(gain).log10()
}

#[test]
fn ffmpeg_summaries_are_read() {
    assert_eq!(
        parse_summary(SUMMARY),
        Some(Measure {
            lufs: -8.3,
            peak: 0.5
        })
    );
    assert_eq!(parse_summary("no summary here"), None);
}

#[test]
fn loud_songs_come_down_and_quiet_ones_go_up_only_to_the_peak_ceiling() {
    // -8.3 LUFS -> -14: 5.7 dB quieter.
    assert!(
        (db(level_gain(Measure {
            lufs: -8.3,
            peak: 0.5
        })) + 5.7)
            .abs()
            < 0.01
    );
    // -22 LUFS with plenty of room: +8 dB.
    assert!(
        (db(level_gain(Measure {
            lufs: -22.0,
            peak: -12.0
        })) - 8.0)
            .abs()
            < 0.01
    );
    // -22 LUFS but peaking at -3 dBTP: only +2 dB (to -1 dBTP).
    assert!(
        (db(level_gain(Measure {
            lufs: -22.0,
            peak: -3.0
        })) - 2.0)
            .abs()
            < 0.01
    );
    // Already at the ceiling: no boost at all.
    assert_eq!(
        level_gain(Measure {
            lufs: -20.0,
            peak: -0.5
        }),
        1.0
    );
    // Silence or nonsense: untouched.
    assert_eq!(
        level_gain(Measure {
            lufs: -90.0,
            peak: -90.0
        }),
        1.0
    );
    assert_eq!(
        level_gain(Measure {
            lufs: f64::NAN,
            peak: 0.0
        }),
        1.0
    );
}

#[test]
fn measurements_are_cached_per_file_and_survive_restarts() {
    let dir = tempfile::tempdir().unwrap();
    let song = dir.path().join("Song.flac");
    fs::write(&song, b"audio").unwrap();
    let broken = dir.path().join("Broken.flac");
    fs::write(&broken, b"x").unwrap();
    let file = dir.path().join("state/loudness.json");

    let cache = LoudnessCache::new(file.clone());
    let songs = vec![song.clone(), broken.clone()];
    assert_eq!(cache.missing(&songs), songs);
    assert!(cache.claim(&song));
    assert!(!cache.claim(&song));
    assert_eq!(cache.missing(&songs), vec![broken.clone()]);
    cache.record(
        &song,
        Some(Measure {
            lufs: -14.0,
            peak: -1.5,
        }),
    );
    cache.record(&broken, None);

    let again = LoudnessCache::new(file);
    assert_eq!(
        again.get(&song),
        Some(Measure {
            lufs: -14.0,
            peak: -1.5
        })
    );
    assert_eq!(again.get(&broken), None);
    assert!(again.missing(&songs).is_empty());
    // A changed file is measured again.
    fs::write(&song, b"new audio").unwrap();
    assert_eq!(again.get(&song), None);
    assert_eq!(again.missing(&songs), vec![song]);
}

/// Uses the bundled ffmpeg when present (Windows dev setup).
#[test]
fn a_real_song_is_measured() {
    let ffmpeg = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("binaries/ffmpeg-x86_64-pc-windows-msvc.exe");
    if !ffmpeg.is_file() {
        return;
    }
    // 5 s of a 1 kHz tone at -18 dBFS (long enough to gate; the fixtures are < 0.4 s).
    let dir = tempfile::tempdir().unwrap();
    let song = dir.path().join("Tone.flac");
    let status = std::process::Command::new(&ffmpeg)
        .args([
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=5",
        ])
        .arg(&song)
        .status()
        .unwrap();
    assert!(status.success());
    let measured = measure(&ffmpeg, &song).unwrap();
    assert!(
        measured.lufs > -30.0 && measured.lufs < -15.0,
        "{measured:?}"
    );
    assert!(
        measured.peak < -15.0 && measured.peak > -25.0,
        "{measured:?}"
    );
    assert!(level_gain(measured) > 1.0);
}
