//! Playback preparation with the real bundled FFmpeg. Ignored by default (CI
//! has empty stand-in binaries); run locally with
//! `cargo test --test preparer -- --ignored`.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::mpsc;
use std::sync::Arc;
use std::time::Duration;

use qtmedia_app::playback::{parse_probe, Support};
use qtmedia_app::preparer::{prune, Prepared, Preparer};
use serde_json::Value;

fn binary(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join(format!("binaries/{name}-x86_64-pc-windows-msvc.exe"))
}

fn make(path: &Path, args: &[&str]) {
    let status = Command::new(binary("ffmpeg"))
        .args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x240:r=25:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=2",
        ])
        .args(args)
        .arg(path)
        .status()
        .unwrap();
    assert!(status.success(), "making {}", path.display());
}

fn codecs(path: &Path) -> (String, String) {
    let output = Command::new(binary("ffprobe"))
        .args([
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
        ])
        .arg(path)
        .output()
        .unwrap();
    let probe = parse_probe(&String::from_utf8_lossy(&output.stdout)).unwrap();
    (
        probe.video.unwrap().codec,
        probe.audio.map(|audio| audio.codec).unwrap_or_default(),
    )
}

#[test]
#[ignore = "needs the real bundled ffmpeg/ffprobe"]
fn prepares_mkv_mov_and_avi_and_plays_mp4_directly() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("library");
    std::fs::create_dir_all(root.join("video")).unwrap();
    let cache = dir.path().join("cache");
    make(
        &root.join("video/direct.mp4"),
        &["-c:v", "libx264", "-c:a", "aac", "-shortest"],
    );
    make(
        &root.join("video/remux.mov"),
        &["-c:v", "libx264", "-c:a", "aac", "-shortest"],
    );
    make(
        &root.join("video/ac3.mkv"),
        &["-c:v", "libx264", "-c:a", "ac3", "-shortest"],
    );
    make(
        &root.join("video/xvid.avi"),
        &["-c:v", "mpeg4", "-c:a", "libmp3lame", "-shortest"],
    );

    let (tx, rx) = mpsc::channel::<Value>();
    let preparer = Preparer::new(
        binary("ffmpeg"),
        binary("ffprobe"),
        cache.clone(),
        Arc::new(move |event| {
            let _ = tx.send(event);
        }),
    );

    assert_eq!(
        preparer.prepare(&root, "video/direct.mp4", Support::default()),
        Ok(Prepared::Direct)
    );
    let expected = [
        ("video/remux.mov", "remux", ("h264", "aac")),
        ("video/ac3.mkv", "transcode", ("h264", "opus")),
        ("video/xvid.avi", "transcode", ("h264", "mp3")),
    ];
    for (relative, mode, (video, audio)) in expected {
        let Prepared::Preparing { id, mode: started } = preparer
            .prepare(&root, relative, Support::default())
            .unwrap()
        else {
            panic!("{relative} should need preparing");
        };
        assert_eq!(started, mode, "{relative}");
        let url = loop {
            let event = rx
                .recv_timeout(Duration::from_secs(60))
                .expect("prepare event");
            if event["id"] != id.as_str() {
                continue;
            }
            match event["type"].as_str() {
                Some("ready") => break event["url"].as_str().unwrap().to_owned(),
                Some("progress") => continue,
                other => panic!("{relative}: {other:?} {event}"),
            }
        };
        assert_eq!(url, format!("playback/{id}.mp4"));
        let copy = cache.join(format!("{id}.mp4"));
        assert_eq!(
            codecs(&copy),
            (video.to_owned(), audio.to_owned()),
            "{relative}"
        );
        // Prepared once: the next request is served from the cache.
        assert_eq!(
            preparer.prepare(&root, relative, Support::default()),
            Ok(Prepared::Ready { url })
        );
    }
    assert!(std::fs::read_dir(&cache).unwrap().all(|entry| !entry
        .unwrap()
        .file_name()
        .to_string_lossy()
        .ends_with(".part")));
    assert_eq!(
        preparer.prepare(&root, "audio/x.mp3", Support::default()),
        Err("unsafe_path")
    );
}

#[test]
fn pruning_removes_the_oldest_copies_and_keeps_the_new_one() {
    let dir = tempfile::tempdir().unwrap();
    let names = ["000000000000000a", "000000000000000b", "000000000000000c"];
    for (index, name) in names.iter().enumerate() {
        let path = dir.path().join(format!("{name}.mp4"));
        std::fs::write(&path, vec![0u8; 100]).unwrap();
        let file = std::fs::File::options().append(true).open(&path).unwrap();
        file.set_modified(std::time::UNIX_EPOCH + Duration::from_secs(1000 + index as u64))
            .unwrap();
    }
    std::fs::write(dir.path().join("notes.txt"), vec![0u8; 500]).unwrap();
    let keep = dir.path().join("000000000000000a.mp4");
    prune(dir.path(), 150, &keep);
    let left: Vec<String> = std::fs::read_dir(dir.path())
        .unwrap()
        .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    assert!(
        left.contains(&"000000000000000a.mp4".to_owned()),
        "kept: {left:?}"
    );
    assert!(
        !left.contains(&"000000000000000b.mp4".to_owned()),
        "{left:?}"
    );
    assert!(
        left.contains(&"notes.txt".to_owned()),
        "unrelated files stay: {left:?}"
    );
}
