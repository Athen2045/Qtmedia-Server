use std::fs;

use qtmedia_app::media::{parse_range, percent_decode, serve, serve_with_limit};

fn library() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for sub in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(dir.path().join(sub)).unwrap();
    }
    fs::write(
        dir.path().join("audio").join("Song A.mp3"),
        (0u8..=99).collect::<Vec<_>>(),
    )
    .unwrap();
    fs::write(dir.path().join("video").join("Clip.mp4"), b"video").unwrap();
    fs::write(dir.path().join("secret.mp3"), b"outside").unwrap();
    dir
}

fn header<'a>(response: &'a qtmedia_app::media::MediaResponse, name: &str) -> Option<&'a str> {
    response
        .headers
        .iter()
        .find(|(key, _)| *key == name)
        .map(|(_, value)| value.as_str())
}

#[test]
fn parses_supported_range_forms() {
    assert_eq!(parse_range("bytes=0-9", 100), Some((0, 9)));
    assert_eq!(parse_range("bytes=90-", 100), Some((90, 99)));
    assert_eq!(parse_range("bytes=-10", 100), Some((90, 99)));
    assert_eq!(parse_range("bytes=50-500", 100), Some((50, 99)));
    assert_eq!(parse_range("bytes=100-", 100), None);
    assert_eq!(parse_range("bytes=5-1", 100), None);
    assert_eq!(parse_range("bytes=0-1,4-5", 100), None);
    assert_eq!(parse_range("items=0-1", 100), None);
}

#[test]
fn decodes_percent_escapes() {
    assert_eq!(
        percent_decode("audio%2FSong%20A.mp3").as_deref(),
        Some("audio/Song A.mp3")
    );
    assert_eq!(percent_decode("bad%2"), None);
}

#[test]
fn serves_whole_and_partial_audio() {
    let dir = library();
    let full = serve(dir.path(), "GET", "/audio%2FSong%20A.mp3", None);
    assert_eq!(full.status, 200);
    assert_eq!(full.body.len(), 100);
    assert_eq!(header(&full, "Content-Type"), Some("audio/mpeg"));

    let part = serve(
        dir.path(),
        "GET",
        "/audio%2FSong%20A.mp3",
        Some("bytes=10-19"),
    );
    assert_eq!(part.status, 206);
    assert_eq!(part.body, (10u8..=19).collect::<Vec<_>>());
    assert_eq!(header(&part, "Content-Range"), Some("bytes 10-19/100"));

    let head = serve(dir.path(), "HEAD", "/audio/Song%20A.mp3", None);
    assert_eq!(head.status, 200);
    assert!(head.body.is_empty());
    assert_eq!(header(&head, "Content-Length"), Some("100"));

    let unsatisfiable = serve(dir.path(), "GET", "/audio/Song%20A.mp3", Some("bytes=500-"));
    assert_eq!(unsatisfiable.status, 416);
}

#[test]
fn serves_flac_with_its_media_type() {
    let dir = library();
    fs::write(dir.path().join("audio").join("Song B.flac"), b"fLaC").unwrap();
    let response = serve(dir.path(), "GET", "/audio%2FSong%20B.flac", None);
    assert_eq!(response.status, 200);
    assert_eq!(header(&response, "Content-Type"), Some("audio/flac"));
    assert_eq!(
        header(
            &serve(dir.path(), "GET", "/audio%2FSong%20A.mp3", None),
            "Content-Type"
        ),
        Some("audio/mpeg")
    );
}

#[test]
fn serves_library_video_with_its_media_type() {
    let dir = library();
    let full = serve(dir.path(), "GET", "/video%2FClip.mp4", None);
    assert_eq!(full.status, 200);
    assert_eq!(header(&full, "Content-Type"), Some("video/mp4"));
    assert_eq!(full.body, b"video");

    let part = serve(dir.path(), "GET", "/video/Clip.mp4", Some("bytes=1-3"));
    assert_eq!(part.status, 206);
    assert_eq!(part.body, b"ide");
    assert_eq!(header(&part, "Content-Range"), Some("bytes 1-3/5"));
}

#[test]
fn every_body_is_bounded_for_large_files() {
    let dir = library();
    let big = vec![7u8; 40];
    fs::write(dir.path().join("video").join("Big.mp4"), &big).unwrap();

    // Closed ranges are clamped and Content-Range reports the actual span.
    let closed = serve_with_limit(dir.path(), "GET", "/video/Big.mp4", Some("bytes=0-39"), 16);
    assert_eq!(closed.status, 206);
    assert_eq!(closed.body.len(), 16);
    assert_eq!(header(&closed, "Content-Range"), Some("bytes 0-15/40"));

    // A request without Range gets a bounded partial response, not 40 bytes.
    let whole = serve_with_limit(dir.path(), "GET", "/video/Big.mp4", None, 16);
    assert_eq!(whole.status, 206);
    assert_eq!(whole.body.len(), 16);
    assert_eq!(header(&whole, "Content-Range"), Some("bytes 0-15/40"));
    assert_eq!(header(&whole, "Content-Length"), Some("16"));

    // Small files are still served whole.
    let small = serve_with_limit(dir.path(), "GET", "/video/Clip.mp4", None, 16);
    assert_eq!(small.status, 200);
}

#[test]
fn refuses_anything_outside_library_audio_and_video() {
    let dir = library();
    fs::write(dir.path().join("video").join("notes.txt"), b"text").unwrap();
    fs::write(dir.path().join("artwork").join("cover.jpg"), b"jpg").unwrap();
    assert_eq!(
        serve(dir.path(), "GET", "/video%2Fnotes.txt", None).status,
        404
    );
    assert_eq!(
        serve(dir.path(), "GET", "/artwork%2Fcover.jpg", None).status,
        403
    );
    assert_eq!(
        serve(dir.path(), "GET", "/video%2F..%2Fsecret.mp3", None).status,
        404
    );
    assert_eq!(
        serve(dir.path(), "GET", "/audio%2F..%2Fsecret.mp3", None).status,
        404
    );
    assert_eq!(
        serve(dir.path(), "GET", "/audio%2F..%5Csecret.mp3", None).status,
        404
    );
    assert_eq!(
        serve(dir.path(), "GET", "/audio%2Fmissing.mp3", None).status,
        404
    );
    assert_eq!(
        serve(dir.path(), "POST", "/audio%2FSong%20A.mp3", None).status,
        405
    );
    assert_eq!(serve(dir.path(), "GET", "/audio%2Fbad%2", None).status, 400);
}

#[test]
fn prepared_copies_are_served_only_by_strict_name_from_the_cache() {
    use qtmedia_app::media::{playback_name, serve_playback};
    let cache = tempfile::tempdir().unwrap();
    std::fs::write(cache.path().join("0123456789abcdef.mp4"), b"prepared").unwrap();
    std::fs::write(cache.path().join("secret.txt"), b"no").unwrap();

    assert_eq!(
        playback_name("/playback%2F0123456789abcdef.mp4").as_deref(),
        Some("0123456789abcdef.mp4")
    );
    assert_eq!(
        playback_name("/playback/0123456789abcdef.mp4").as_deref(),
        Some("0123456789abcdef.mp4")
    );
    for bad in [
        "/playback/../secret.txt",
        "/playback/secret.txt",
        "/playback%2F..%2F..%2Fx.mp4",
        "/video/0123456789abcdef.mp4",
        "/playback/0123456789ABCDEF.mp4",
    ] {
        assert_eq!(playback_name(bad), None, "{bad}");
        assert_eq!(
            serve_playback(cache.path(), "GET", bad, None).status,
            404,
            "{bad}"
        );
    }

    let full = serve_playback(
        cache.path(),
        "GET",
        "/playback%2F0123456789abcdef.mp4",
        None,
    );
    assert_eq!(full.status, 200);
    assert_eq!(full.body, b"prepared");
    assert!(full
        .headers
        .contains(&("Content-Type", "video/mp4".to_owned())));
    let part = serve_playback(
        cache.path(),
        "GET",
        "/playback/0123456789abcdef.mp4",
        Some("bytes=2-4"),
    );
    assert_eq!((part.status, part.body.as_slice()), (206, &b"epa"[..]));
    assert_eq!(
        serve_playback(cache.path(), "POST", "/playback/0123456789abcdef.mp4", None).status,
        405
    );
    assert_eq!(
        serve_playback(cache.path(), "GET", "/playback/fedcba9876543210.mp4", None).status,
        404
    );
}

#[test]
fn media_is_cors_readable_only_by_the_app_itself() {
    use qtmedia_app::media::allowed_origin;
    assert_eq!(
        allowed_origin(Some("http://tauri.localhost")),
        Some("http://tauri.localhost")
    );
    assert_eq!(
        allowed_origin(Some("tauri://localhost")),
        Some("tauri://localhost")
    );
    assert_eq!(
        allowed_origin(Some("http://localhost:1420")),
        Some("http://localhost:1420")
    );
    for other in [
        "https://evil.example",
        "http://localhost:8080",
        "null",
        "http://tauri.localhost.evil.example",
    ] {
        assert_eq!(allowed_origin(Some(other)), None, "{other}");
    }
    assert_eq!(allowed_origin(None), None);
}
