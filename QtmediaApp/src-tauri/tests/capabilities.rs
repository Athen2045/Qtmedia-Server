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
    assert!(!csp.contains("https:"));
}
