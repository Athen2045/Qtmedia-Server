use qtmedia_app::settings::{
    load_network, save_preference, validate_proxy, CookieSource, DohProvider, LibraryPreference,
    NetworkPreference,
};
use qtmedia_app::sidecar::engine_network_env;

#[test]
fn preferences_saved_before_network_settings_load_with_network_off() {
    let temp = tempfile::tempdir().unwrap();
    let preference = temp.path().join("preferences.json");
    std::fs::write(&preference, br#"{"version":1,"custom_root":null}"#).unwrap();

    assert_eq!(load_network(&preference), NetworkPreference::default());
}

#[test]
fn network_settings_survive_a_library_switch_and_reload() {
    let temp = tempfile::tempdir().unwrap();
    let preference = temp.path().join("preferences.json");
    let network = NetworkPreference {
        doh: DohProvider::Cloudflare,
        proxy: Some("socks5h://127.0.0.1:1080".into()),
        cookies: CookieSource::Firefox,
    };
    let custom_root = temp.path().join("Media").join("Qtmedia").join("library");

    save_preference(
        &preference,
        &LibraryPreference::custom(custom_root).with_network(network.clone()),
    )
    .unwrap();

    assert_eq!(load_network(&preference), network);
}

#[test]
fn an_invalid_stored_proxy_is_dropped_rather_than_used() {
    let temp = tempfile::tempdir().unwrap();
    let preference = temp.path().join("preferences.json");
    std::fs::write(
        &preference,
        br#"{"version":1,"custom_root":null,"network":{"doh":"quad9","proxy":"ftp://x:21"}}"#,
    )
    .unwrap();

    let loaded = load_network(&preference);

    assert_eq!(loaded.doh, DohProvider::Quad9);
    assert_eq!(loaded.proxy, None);
}

#[test]
fn proxy_urls_must_name_a_supported_scheme_host_and_port() {
    assert_eq!(validate_proxy("").unwrap(), None);
    assert_eq!(validate_proxy("  ").unwrap(), None);
    assert_eq!(
        validate_proxy(" socks5h://127.0.0.1:1080 ").unwrap(),
        Some("socks5h://127.0.0.1:1080".into())
    );
    assert!(validate_proxy("http://user:secret@proxy.example:8080").is_ok());
    for invalid in [
        "ftp://proxy.example:21",
        "socks5://proxy.example",
        "proxy.example:8080",
        "http://proxy example:8080",
        "http://:8080",
    ] {
        assert!(
            validate_proxy(invalid).is_err(),
            "{invalid} should be rejected"
        );
    }
}

#[test]
fn doh_providers_use_ip_endpoints_that_need_no_system_dns() {
    assert_eq!(DohProvider::Off.url(), None);
    assert_eq!(
        DohProvider::Cloudflare.url(),
        Some("https://1.1.1.1/dns-query")
    );
    assert_eq!(DohProvider::Google.url(), Some("https://8.8.8.8/dns-query"));
    assert_eq!(DohProvider::Quad9.url(), Some("https://9.9.9.9/dns-query"));
}

#[test]
fn the_engine_receives_only_the_configured_network_settings() {
    assert!(engine_network_env(&NetworkPreference::default()).is_empty());
    assert_eq!(
        engine_network_env(&NetworkPreference {
            doh: DohProvider::Google,
            proxy: Some("http://proxy.example:8080".into()),
            cookies: CookieSource::Firefox,
        }),
        vec![
            ("QTMEDIA_DOH", "https://8.8.8.8/dns-query".to_owned()),
            ("QTMEDIA_PROXY", "http://proxy.example:8080".to_owned()),
            ("QTMEDIA_COOKIES_BROWSER", "firefox".to_owned()),
        ]
    );
}

#[test]
fn cookie_mode_defaults_to_off_and_loads_a_saved_firefox_choice() {
    let temp = tempfile::tempdir().unwrap();
    let preference = temp.path().join("preferences.json");
    std::fs::write(
        &preference,
        br#"{"version":1,"custom_root":null,"network":{"doh":"off","proxy":null}}"#,
    )
    .unwrap();
    assert_eq!(load_network(&preference).cookies, CookieSource::Off);

    std::fs::write(
        &preference,
        br#"{"version":1,"custom_root":null,"network":{"cookies":"firefox"}}"#,
    )
    .unwrap();
    assert_eq!(load_network(&preference).cookies, CookieSource::Firefox);
    assert_eq!(CookieSource::Off.browser(), None);
}
