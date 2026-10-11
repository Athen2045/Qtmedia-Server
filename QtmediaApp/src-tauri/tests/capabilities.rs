use std::fs;

#[test]
fn frontend_capability_has_no_shell_or_unrestricted_opener_access() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let raw = fs::read_to_string(root.join("capabilities/default.json")).unwrap();
    let value: serde_json::Value = serde_json::from_str(&raw).unwrap();
    let permissions = value["permissions"].as_array().unwrap();
    assert!(permissions.iter().all(|permission| {
        let rendered = permission.to_string();
        !rendered.contains("shell:") && !rendered.contains("opener:")
    }));
}

#[test]
fn frameless_window_can_be_dragged_by_its_drag_regions() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let raw = fs::read_to_string(root.join("capabilities/default.json")).unwrap();
    let value: serde_json::Value = serde_json::from_str(&raw).unwrap();
    let permissions: Vec<&str> = value["permissions"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|permission| permission.as_str())
        .collect();
    // Without these, `data-tauri-drag-region` silently does nothing.
    assert!(permissions.contains(&"core:window:allow-start-dragging"));
    assert!(permissions.contains(&"core:window:allow-internal-toggle-maximize"));
}

#[test]
fn csp_allows_only_the_bounded_artwork_data_transport_added_by_rust() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let raw = fs::read_to_string(root.join("tauri.conf.json")).unwrap();
    let value: serde_json::Value = serde_json::from_str(&raw).unwrap();
    let csp = value["app"]["security"]["csp"].as_str().unwrap();
    let image_directive = csp
        .split(';')
        .find(|part| part.trim().starts_with("img-src"))
        .unwrap();
    assert!(image_directive
        .split_whitespace()
        .any(|source| source == "data:"));
    // The only remote origin is the lyrics service, and only for fetch().
    let remote: Vec<&str> = csp
        .split_whitespace()
        .filter(|source| source.starts_with("https:"))
        .collect();
    assert_eq!(remote, ["https://lrclib.net"]);
    let connect = csp
        .split(';')
        .find(|part| part.trim().starts_with("connect-src"))
        .unwrap();
    assert!(connect
        .split_whitespace()
        .any(|source| source == "https://lrclib.net"));
}

#[test]
fn csp_limits_media_to_the_qtmedia_audio_scheme() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let raw = fs::read_to_string(root.join("tauri.conf.json")).unwrap();
    let value: serde_json::Value = serde_json::from_str(&raw).unwrap();
    let csp = value["app"]["security"]["csp"].as_str().unwrap();
    let media: Vec<&str> = csp
        .split(';')
        .find(|part| part.trim().starts_with("media-src"))
        .unwrap()
        .split_whitespace()
        .skip(1)
        .collect();
    assert_eq!(media, ["'self'", "qtmedia:", "http://qtmedia.localhost"]);
    // The general asset protocol is never opened for media.
    assert!(!media.contains(&"asset:"));
}
