use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use qtmedia_app::media::{serve_subtitle, subtitle_name};
use qtmedia_app::removal::remove_entries;
use qtmedia_app::subtitles::{
    add_files, decode_text, describe_middle, is_cache_file_name, parse_streams, read_subtitles,
    srt_to_vtt,
};

fn library() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for folder in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(dir.path().join(folder)).unwrap();
    }
    dir
}

const SRT: &str = "1\r\n00:00:01,000 --> 00:00:02,500\r\n<font color=\"#fff\">Hello</font> <i>there</i>\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nBye\r\n";

#[test]
fn srt_becomes_webvtt() {
    let vtt = srt_to_vtt(SRT);
    assert!(vtt.starts_with("WEBVTT\n\n"));
    assert!(vtt.contains("00:00:01.000 --> 00:00:02.500\n"));
    assert!(vtt.contains("Hello <i>there</i>\n"));
    assert!(!vtt.contains("font"));
    assert!(!vtt.contains('\r'));
}

#[test]
fn utf16_and_bom_text_is_read() {
    let mut bytes = vec![0xFF, 0xFE];
    for unit in "Olá".encode_utf16() {
        bytes.extend(unit.to_le_bytes());
    }
    assert_eq!(decode_text(&bytes), "Olá");
    assert_eq!(decode_text(b"\xEF\xBB\xBFHi"), "Hi");
}

#[test]
fn file_name_parts_become_language_and_label() {
    assert_eq!(describe_middle(""), (None, None));
    assert_eq!(describe_middle("en"), (None, Some("en".into())));
    assert_eq!(describe_middle("pt-BR"), (None, Some("pt-BR".into())));
    assert_eq!(
        describe_middle("en.forced"),
        (Some("forced".into()), Some("en".into()))
    );
    assert_eq!(describe_middle("English"), (Some("English".into()), None));
}

#[test]
fn embedded_streams_are_sorted_into_text_and_pictures() {
    let json = r#"{"streams":[
        {"index":2,"codec_name":"subrip","tags":{"language":"eng","title":"Full"}},
        {"index":3,"codec_name":"hdmv_pgs_subtitle","tags":{"language":"fre"}},
        {"index":4,"codec_name":"ass","tags":{"LANGUAGE":"und"}}
    ]}"#;
    let streams = parse_streams(json);
    assert_eq!(streams.len(), 3);
    assert!(streams[0].text && !streams[1].text && streams[2].text);
    assert_eq!(streams[0].language.as_deref(), Some("eng"));
    assert_eq!(streams[0].title.as_deref(), Some("Full"));
    assert_eq!(streams[2].language, None);
    assert!(parse_streams("not json").is_empty());
}

#[test]
fn advert_and_shared_titles_are_dropped() {
    let shared = r#"{"streams":[
        {"index":2,"codec_name":"subrip","tags":{"language":"eng","title":"T4TSA.cc - Download Movies"}},
        {"index":3,"codec_name":"subrip","tags":{"language":"eng","title":"T4TSA.cc - Download Movies"}}
    ]}"#;
    assert!(parse_streams(shared)
        .iter()
        .all(|stream| stream.title.is_none()));
    let mixed = r#"{"streams":[
        {"index":2,"codec_name":"subrip","tags":{"title":"SDH"}},
        {"index":3,"codec_name":"subrip","tags":{"title":"Visit www.example.com"}},
        {"index":4,"codec_name":"subrip","tags":{"title":"Signs & Songs"}}
    ]}"#;
    let titles: Vec<Option<String>> = parse_streams(mixed)
        .into_iter()
        .map(|stream| stream.title)
        .collect();
    assert_eq!(
        titles,
        [Some("SDH".into()), None, Some("Signs & Songs".into())]
    );
}

#[test]
fn files_beside_a_video_are_converted_and_served_from_the_cache() {
    let dir = library();
    let root = dir.path();
    let cache = tempfile::tempdir().unwrap();
    fs::write(root.join("video/Film.mp4"), b"video").unwrap();
    fs::write(root.join("video/Film.en.srt"), SRT).unwrap();
    fs::write(
        root.join("video/Film.Director.VTT"),
        "00:00:01.000 --> 00:00:02.000\nNote\n",
    )
    .unwrap();
    fs::write(root.join("video/Film 2.en.srt"), SRT).unwrap(); // another video's
    fs::write(root.join("video/Film.en.txt"), "not subtitles").unwrap();

    let result = read_subtitles(root, "video/Film.mp4", cache.path(), None, None).unwrap();

    let ids: Vec<&str> = result
        .tracks
        .iter()
        .map(|track| track.id.as_str())
        .collect();
    assert_eq!(ids, ["file:Film.Director.VTT", "file:Film.en.srt"]);
    assert_eq!(result.tracks[1].language.as_deref(), Some("en"));
    assert_eq!(result.tracks[0].label.as_deref(), Some("Director"));
    let url = &result.tracks[0].url;
    let name = url.strip_prefix("subtitles/").unwrap();
    assert!(is_cache_file_name(name));
    assert!(fs::read_to_string(cache.path().join(name))
        .unwrap()
        .starts_with("WEBVTT"));

    // Served over qtmedia:// as text/vtt; anything else in the cache is refused.
    assert_eq!(subtitle_name(&format!("/{url}")).as_deref(), Some(name));
    let served = serve_subtitle(cache.path(), "GET", &format!("/{url}"));
    assert_eq!(served.status, 200);
    assert!(served
        .headers
        .iter()
        .any(|(key, value)| *key == "Content-Type" && value.starts_with("text/vtt")));
    assert!(subtitle_name("/subtitles/../secret.vtt").is_none());
    assert!(subtitle_name("/subtitles/Film.en.vtt").is_none());
    assert_eq!(
        serve_subtitle(cache.path(), "POST", &format!("/{url}")).status,
        405
    );
}

#[test]
fn only_library_videos_are_read() {
    let dir = library();
    let cache = tempfile::tempdir().unwrap();
    assert_eq!(
        read_subtitles(dir.path(), "audio/Song.mp3", cache.path(), None, None),
        Err("unsafe_path")
    );
    assert_eq!(
        read_subtitles(dir.path(), "video/../../x.mp4", cache.path(), None, None),
        Err("unsafe_path")
    );
    assert_eq!(
        read_subtitles(dir.path(), "video/Missing.mp4", cache.path(), None, None),
        Err("not_found")
    );
}

#[test]
fn picked_files_are_copied_beside_the_video() {
    let dir = library();
    let root = dir.path();
    let outside = tempfile::tempdir().unwrap();
    fs::write(root.join("video/Film.mkv"), b"video").unwrap();
    let english = outside.path().join("English.srt");
    let notes = outside.path().join("notes.txt");
    fs::write(&english, SRT).unwrap();
    fs::write(&notes, "x").unwrap();

    assert_eq!(
        add_files(root, "video/Film.mkv", &[english.clone(), notes]).unwrap(),
        1
    );
    assert_eq!(add_files(root, "video/Film.mkv", &[english]).unwrap(), 1);
    assert!(root.join("video/Film.English.srt").is_file());
    assert!(root.join("video/Film.English 2.srt").is_file());
    assert_eq!(add_files(root, "audio/Song.mp3", &[]), Err("unsafe_path"));
}

#[test]
fn deleting_a_video_takes_its_subtitles_unless_another_video_shares_them() {
    let dir = library();
    let root = dir.path();
    fs::write(root.join("video/Film.mp4"), b"video").unwrap();
    fs::write(root.join("video/Film.mkv"), b"video").unwrap();
    fs::write(root.join("video/Film.en.srt"), SRT).unwrap();
    let remove = |path: &Path| fs::remove_file(path).is_ok();

    remove_entries(root, &["video/Film.mp4".to_owned()], remove);
    assert!(root.join("video/Film.en.srt").is_file());
    remove_entries(root, &["video/Film.mkv".to_owned()], remove);
    assert!(!root.join("video/Film.en.srt").exists());
}

fn bundled(tool: &str) -> Option<PathBuf> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("binaries")
        .join(format!("{tool}-x86_64-pc-windows-msvc.exe"));
    path.is_file().then_some(path)
}

/// Uses the bundled ffmpeg/ffprobe when they are present (Windows dev setup).
#[test]
fn embedded_text_subtitles_are_extracted_in_one_pass() {
    let (Some(ffmpeg), Some(ffprobe)) = (bundled("ffmpeg"), bundled("ffprobe")) else {
        eprintln!("bundled ffmpeg/ffprobe not found; skipped");
        return;
    };
    let dir = library();
    let root = dir.path();
    let cache = tempfile::tempdir().unwrap();
    let srt_en = root.join("temp/en.srt");
    let srt_fr = root.join("temp/fr.srt");
    fs::write(&srt_en, SRT).unwrap();
    fs::write(&srt_fr, SRT.replace("Hello", "Bonjour")).unwrap();
    let status = Command::new(&ffmpeg)
        .args([
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x36:d=5",
        ])
        .arg("-i")
        .arg(&srt_en)
        .arg("-i")
        .arg(&srt_fr)
        .args([
            "-map",
            "0:v",
            "-map",
            "1:s",
            "-map",
            "2:s",
            "-c:v",
            "libx264",
            "-c:s",
            "srt",
            "-metadata:s:s:0",
            "language=eng",
            "-metadata:s:s:1",
            "language=fre",
            "-metadata:s:s:1",
            "title=French",
        ])
        .arg(root.join("video/Clip.mkv"))
        .status()
        .unwrap();
    assert!(status.success());

    let result = read_subtitles(
        root,
        "video/Clip.mkv",
        cache.path(),
        Some(&ffprobe),
        Some(&ffmpeg),
    )
    .unwrap();

    assert_eq!(result.unsupported, 0);
    let tracks: Vec<(Option<&str>, Option<&str>)> = result
        .tracks
        .iter()
        .map(|track| (track.language.as_deref(), track.label.as_deref()))
        .collect();
    assert_eq!(tracks, [(Some("eng"), None), (Some("fre"), Some("French"))]);
    let french = fs::read_to_string(
        cache
            .path()
            .join(result.tracks[1].url.strip_prefix("subtitles/").unwrap()),
    )
    .unwrap();
    assert!(french.starts_with("WEBVTT"));
    assert!(french.contains("Bonjour"));
    // A second read reuses the cache (no new extraction needed).
    let again = read_subtitles(root, "video/Clip.mkv", cache.path(), Some(&ffprobe), None).unwrap();
    assert_eq!(again.tracks.len(), 2);
}
