//! Task 5: path confinement, the saved audio preference, engine settings,
//! device fallback, and `audio-event` payloads.

use std::fs;
use std::path::{Path, PathBuf};

use qtmedia_app::audio::decoder::{Codec, SourceFormat};
use qtmedia_app::audio::engine::{Event, PlayState};
use qtmedia_app::audio::format::{Negotiated, OutputMode, PcmFormat, RateMismatch, Reason};
use qtmedia_app::audio::output::{DeviceInfo, Transport};
use qtmedia_app::audio::service::{
    device_json, effective_device, engine_settings, event_payload, relative_audio_path,
    resolve_audio_path,
};
use qtmedia_app::paths::PathError;
use qtmedia_app::settings::{
    load_audio, load_network, load_preference, save_audio, save_preference, validate_audio,
    AudioMode, AudioPreference, DohProvider, LibraryPreference, NetworkPreference,
    RateMismatchPreference,
};
use serde_json::json;

fn library() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("Qtmedia").join("library");
    for sub in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(root.join(sub)).unwrap();
    }
    fs::write(root.join("audio/Song.flac"), b"x").unwrap();
    fs::write(root.join("video/Clip.mp4"), b"x").unwrap();
    fs::write(dir.path().join("outside.flac"), b"x").unwrap();
    dir
}

fn root(dir: &tempfile::TempDir) -> PathBuf {
    dir.path().join("Qtmedia").join("library")
}

#[test]
fn only_library_audio_can_be_played() {
    let dir = library();
    let root = root(&dir);
    assert!(resolve_audio_path(&root, "audio/Song.flac").is_ok());
    assert_eq!(
        resolve_audio_path(&root, "video/Clip.mp4"),
        Err(PathError::UnsafePath)
    );
    for escape in [
        "audio/../../../outside.flac",
        "../outside.flac",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "audio/..\\..\\outside.flac",
    ] {
        assert!(resolve_audio_path(&root, escape).is_err(), "{escape}");
    }
    assert_eq!(
        resolve_audio_path(&root, "audio/missing.flac"),
        Err(PathError::NotFound)
    );
}

#[test]
fn engine_paths_become_library_relative() {
    let dir = library();
    let root = root(&dir);
    assert_eq!(
        relative_audio_path(&root, &root.join("audio/Song.flac")).as_deref(),
        Some("audio/Song.flac")
    );
    assert_eq!(
        relative_audio_path(&root, &dir.path().join("outside.flac")),
        None
    );
    assert_eq!(
        relative_audio_path(&root, &root.join("video/Clip.mp4")),
        None
    );
}

#[test]
fn audio_preference_defaults_to_shared_on_the_default_device() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("preferences.json");
    assert_eq!(load_audio(&path), AudioPreference::default());
    assert_eq!(
        AudioPreference::default(),
        AudioPreference {
            device_id: None,
            mode: AudioMode::Shared,
            rate_mismatch: RateMismatchPreference::Strict,
            exclusive_volume: false,
        }
    );
    // A preferences file written before the audio engine loads as defaults.
    fs::write(
        &path,
        r#"{"version":1,"custom_root":null,"network":{"doh":"cloudflare","proxy":null}}"#,
    )
    .unwrap();
    assert_eq!(load_audio(&path), AudioPreference::default());
    assert_eq!(load_network(&path).doh, DohProvider::Cloudflare);
}

#[test]
fn audio_preference_round_trips_and_keeps_library_and_network() {
    let dir = library();
    let path = dir.path().join("preferences.json");
    let custom = root(&dir);
    let network = NetworkPreference {
        doh: DohProvider::Quad9,
        proxy: None,
        ..NetworkPreference::default()
    };
    save_preference(
        &path,
        &LibraryPreference::custom(custom.clone()).with_network(network.clone()),
    )
    .unwrap();

    let audio = AudioPreference {
        device_id: Some("{0.0.0.00000000}.{abc}".into()),
        mode: AudioMode::Exclusive,
        rate_mismatch: RateMismatchPreference::Resample,
        exclusive_volume: true,
    };
    save_audio(&path, audio.clone()).unwrap();
    assert_eq!(load_audio(&path), audio);
    assert_eq!(load_network(&path), network);
    assert_eq!(
        load_preference(&path, Path::new("default")).unwrap().root,
        custom
    );

    // A library or network change (which saves without audio) keeps it.
    save_preference(&path, &LibraryPreference::default().with_network(network)).unwrap();
    assert_eq!(load_audio(&path), audio);
    let text = fs::read_to_string(&path).unwrap();
    assert!(text.contains(r#""mode":"exclusive""#), "{text}");
    assert!(text.contains(r#""rateMismatch":"resample""#), "{text}");
}

#[test]
fn audio_settings_are_validated() {
    let ok = |id: &str| {
        validate_audio(AudioPreference {
            device_id: Some(id.into()),
            ..AudioPreference::default()
        })
    };
    assert_eq!(ok("   ").unwrap().device_id, None);
    assert!(ok("{0.0.0.00000000}.{6f1e}").is_ok());
    assert!(ok("bad id").is_err());
    assert!(ok("bad\nid").is_err());
    assert!(ok(&"x".repeat(600)).is_err());

    let parsed: Result<AudioPreference, _> =
        serde_json::from_str(r#"{"mode":"loud","rateMismatch":"strict"}"#);
    assert!(parsed.is_err());
    let parsed: AudioPreference = serde_json::from_str(r#"{"mode":"exclusive"}"#).unwrap();
    assert_eq!(parsed.mode, AudioMode::Exclusive);
    assert_eq!(parsed.rate_mismatch, RateMismatchPreference::Strict);
}

#[test]
fn an_unreadable_preferences_file_is_never_replaced() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("preferences.json");
    fs::write(&path, b"{ not json").unwrap();
    assert!(save_audio(&path, AudioPreference::default()).is_err());
    assert_eq!(fs::read(&path).unwrap(), b"{ not json");
    // An invalid saved device falls back to defaults on load.
    fs::write(
        &path,
        r#"{"version":1,"custom_root":null,"audio":{"deviceId":"has space","mode":"exclusive"}}"#,
    )
    .unwrap();
    assert_eq!(load_audio(&path), AudioPreference::default());
}

fn device(id: &str, transport: Transport, is_default: bool) -> DeviceInfo {
    DeviceInfo {
        id: id.into(),
        name: format!("Device {id}"),
        transport,
        is_default,
    }
}

#[test]
fn a_missing_chosen_device_falls_back_to_the_default() {
    let devices = [
        device("speakers", Transport::Wired, true),
        device("dac", Transport::Wired, false),
    ];
    let chosen = AudioPreference {
        device_id: Some("dac".into()),
        mode: AudioMode::Exclusive,
        ..AudioPreference::default()
    };
    assert_eq!(effective_device(&chosen, &devices).as_deref(), Some("dac"));
    assert_eq!(effective_device(&chosen, &devices[..1]), None);
    assert_eq!(
        effective_device(&AudioPreference::default(), &devices),
        None
    );

    let settings = engine_settings(&chosen, Some("dac".into()));
    assert_eq!(settings.device.as_deref(), Some("dac"));
    assert_eq!(settings.mode, OutputMode::Exclusive);
    assert_eq!(settings.rate_mismatch, RateMismatch::Strict);
    assert!(!settings.exclusive_volume);
}

#[test]
fn device_list_entries_name_their_transport() {
    assert_eq!(
        device_json(&device("bt", Transport::BluetoothHandsFree, false)),
        json!({"id": "bt", "name": "Device bt", "transport": "bluetoothHandsFree", "isDefault": false})
    );
}

fn flac() -> SourceFormat {
    SourceFormat {
        codec: Codec::Flac,
        sample_rate: 96_000,
        channels: 2,
        bits_per_sample: Some(24),
        total_frames: Some(96_000),
    }
}

#[test]
fn audio_events_use_library_relative_paths_and_stable_fields() {
    let dir = library();
    let root = root(&dir);
    let song = root.join("audio/Song.flac");

    assert_eq!(
        event_payload(&Event::State(PlayState::Playing), &root, None),
        json!({"type": "state", "state": "playing"})
    );
    let started = event_payload(
        &Event::TrackStarted {
            path: song.clone(),
            duration: Some(1.0),
            source: flac(),
        },
        &root,
        None,
    );
    assert_eq!(started["path"], "audio/Song.flac");
    assert_eq!(
        started["source"],
        json!({"codec": "flac", "sampleRate": 96000, "channels": 2, "bitsPerSample": 24})
    );
    let outside = event_payload(
        &Event::TrackEnded {
            path: dir.path().join("outside.flac"),
        },
        &root,
        None,
    );
    assert_eq!(outside["path"], serde_json::Value::Null);
    assert!(!outside.to_string().contains("outside"));

    let negotiated = Negotiated {
        mode: OutputMode::Exclusive,
        output: PcmFormat::int(96_000, 2, 32, 24),
        gain: 1.0,
        bit_perfect: true,
        reason: None,
    };
    let signal = event_payload(
        &Event::SignalPath {
            source: flac(),
            negotiated,
        },
        &root,
        Some(&device("dac", Transport::Wired, false)),
    );
    assert_eq!(signal["output"]["mode"], "exclusive");
    assert_eq!(signal["output"]["bits"], 24);
    assert_eq!(signal["output"]["containerBits"], 32);
    assert_eq!(signal["bitPerfect"], true);
    assert_eq!(signal["reason"], serde_json::Value::Null);
    assert_eq!(
        signal["device"],
        json!({"name": "Device dac", "transport": "wired"})
    );

    let shared = event_payload(
        &Event::SignalPath {
            source: flac(),
            negotiated: Negotiated::shared(PcmFormat::float(48_000, 2), 1.0, Reason::SharedMode),
        },
        &root,
        Some(&device("airbass", Transport::Bluetooth, true)),
    );
    assert_eq!(shared["bitPerfect"], false);
    assert_eq!(shared["reason"], "shared_mode");
    assert_eq!(shared["device"]["transport"], "bluetooth");
    assert_eq!(
        event_payload(
            &Event::Error {
                code: "audio_device_lost"
            },
            &root,
            None
        ),
        json!({"type": "error", "code": "audio_device_lost"})
    );
}
