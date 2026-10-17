use std::fs;
use std::path::PathBuf;
use std::process::Command;

use qtmedia_app::covers::{cover_filter, cover_point, has_cover_for, make_cover, CoverJobs};

fn library() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for folder in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(dir.path().join(folder)).unwrap();
    }
    dir
}

#[test]
fn the_cover_point_is_stable_and_inside_the_video() {
    let at = cover_point("video/Film.mkv", Some(1000.0));
    assert_eq!(at, cover_point("video/Film.mkv", Some(1000.0)));
    assert!((150.0..600.0).contains(&at));
    assert_ne!(at, cover_point("video/Other.mkv", Some(1000.0)));
    assert_eq!(cover_point("video/Short.mp4", Some(2.0)), 1.0);
    assert_eq!(cover_point("video/Unknown.mp4", None), 10.0);
}

#[test]
fn jobs_run_once_and_failures_are_not_retried() {
    let jobs = CoverJobs::default();
    assert!(jobs.claim("video/A.mp4"));
    assert!(!jobs.claim("video/A.mp4"));
    jobs.finish("video/A.mp4", false);
    assert!(!jobs.claim("video/A.mp4"));
    assert!(jobs.claim("video/B.mp4"));
    jobs.finish("video/B.mp4", true);
    assert!(jobs.claim("video/B.mp4"));
}

#[test]
fn an_existing_cover_is_never_replaced() {
    let dir = library();
    let root = dir.path();
    fs::write(root.join("video/Film.mp4"), b"video").unwrap();
    fs::write(root.join("artwork/Film.webp"), b"cover").unwrap();
    assert!(has_cover_for(root, "video/Film.mp4"));
    // No ffmpeg is needed: it returns before running anything.
    assert_eq!(
        make_cover(
            root,
            "video/Film.mp4",
            Some(60.0),
            &PathBuf::from("missing-ffmpeg"),
            None
        ),
        None
    );
    assert_eq!(fs::read(root.join("artwork/Film.webp")).unwrap(), b"cover");
    assert_eq!(
        make_cover(
            root,
            "audio/Song.mp3",
            None,
            &PathBuf::from("missing-ffmpeg"),
            None
        ),
        None
    );
}

/// Uses the bundled ffmpeg when present (Windows dev setup).
#[test]
fn a_frame_becomes_the_cover() {
    let ffmpeg = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("binaries/ffmpeg-x86_64-pc-windows-msvc.exe");
    if !ffmpeg.is_file() {
        eprintln!("bundled ffmpeg not found; skipped");
        return;
    }
    let dir = library();
    let root = dir.path();
    let status = Command::new(&ffmpeg)
        .args([
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=320x180:d=8",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ])
        .arg(root.join("video/Clip.mkv"))
        .status()
        .unwrap();
    assert!(status.success());

    // A wrong (too long) duration still yields a frame from the start.
    let cover = make_cover(root, "video/Clip.mkv", Some(3600.0), &ffmpeg, None);

    assert_eq!(cover.as_deref(), Some("artwork/Clip.jpg"));
    let bytes = fs::read(root.join("artwork/Clip.jpg")).unwrap();
    assert_eq!(&bytes[..2], &[0xFF, 0xD8]);
    assert!(fs::read_dir(root.join("temp")).unwrap().next().is_none());
    // Done once: a second call leaves the cover alone.
    assert_eq!(
        make_cover(root, "video/Clip.mkv", Some(8.0), &ffmpeg, None),
        None
    );
}

#[test]
fn hdr_frames_are_tone_mapped() {
    assert!(cover_filter(Some("smpte2084")).contains("tonemap=hable"));
    assert!(cover_filter(Some("arib-std-b67")).contains("tonemap=hable"));
    assert!(!cover_filter(Some("bt709")).contains("tonemap"));
    assert!(!cover_filter(None).contains("tonemap"));
    assert!(cover_filter(None).starts_with("thumbnail=48,"));
}
