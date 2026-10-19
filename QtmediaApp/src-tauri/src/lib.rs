pub mod audio;
pub mod audio_commands;
pub mod commands;
pub mod covers;
pub mod durations;
pub mod import;
pub mod loudness;
pub mod lyrics;
pub mod media;
pub mod names;
pub mod paths;
pub mod playback;
pub mod preparer;
pub mod protocol;
pub mod removal;
pub mod settings;
pub mod sidecar;
pub mod subtitles;
pub mod vault;
pub mod vault_commands;

use std::sync::Arc;

use tauri::{Emitter, Manager};

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_opener::Builder::new()
                .open_js_links_on_click(false)
                .build(),
        )
        .register_asynchronous_uri_scheme_protocol(media::SCHEME, |ctx, request, responder| {
            let app = ctx.app_handle().clone();
            std::thread::spawn(move || {
                let origin = request
                    .headers()
                    .get("origin")
                    .and_then(|value| value.to_str().ok())
                    .map(str::to_owned);
                let range = request
                    .headers()
                    .get("range")
                    .and_then(|value| value.to_str().ok())
                    .map(str::to_owned);
                let playback = media::playback_name(request.uri().path()).and_then(|_| {
                    app.try_state::<Arc<preparer::Preparer>>().map(|preparer| {
                        media::serve_playback(
                            preparer.cache_dir(),
                            request.method().as_str(),
                            request.uri().path(),
                            range.as_deref(),
                        )
                    })
                });
                // Private folder videos: decrypted per range, only while unlocked.
                let playback = playback.or_else(|| {
                    let (id, extension) = media::vault_request(request.uri().path())?;
                    let root = app.try_state::<commands::AppState>()?.library_root().ok()?;
                    let session = app.try_state::<Arc<vault_commands::VaultSession>>()?;
                    let served = match session.key_for(&root) {
                        Some(key) => match vault::Vault::of_library(&root).reader(&key, &id) {
                            Ok(reader) => media::serve_vault(
                                reader,
                                &extension,
                                request.method().as_str(),
                                range.as_deref(),
                            ),
                            Err(_) => media::MediaResponse {
                                status: 404,
                                headers: Vec::new(),
                                body: Vec::new(),
                            },
                        },
                        None => media::MediaResponse {
                            status: 403,
                            headers: Vec::new(),
                            body: Vec::new(),
                        },
                    };
                    Some(served)
                });
                let playback = playback.or_else(|| {
                    media::subtitle_name(request.uri().path()).and_then(|_| {
                        app.try_state::<subtitles::SubtitleCache>().map(|cache| {
                            media::serve_subtitle(
                                &cache.0,
                                request.method().as_str(),
                                request.uri().path(),
                            )
                        })
                    })
                });
                let served = match (
                    playback,
                    app.try_state::<commands::AppState>()
                        .map(|state| state.library_root()),
                ) {
                    (Some(served), _) => served,
                    (None, Some(Ok(root))) => media::serve(
                        &root,
                        request.method().as_str(),
                        request.uri().path(),
                        range.as_deref(),
                    ),
                    (None, _) => media::MediaResponse {
                        status: 503,
                        headers: Vec::new(),
                        body: Vec::new(),
                    },
                };
                let mut builder = tauri::http::Response::builder().status(served.status);
                if let Some(origin) = media::allowed_origin(origin.as_deref()) {
                    builder = builder
                        .header("Access-Control-Allow-Origin", origin)
                        .header("Vary", "Origin");
                }
                for (name, value) in served.headers {
                    builder = builder.header(name, value);
                }
                responder.respond(builder.body(served.body).unwrap_or_default());
            });
        })
        .setup(|app| {
            let app_data = app.path().app_data_dir()?.join("Qtmedia");
            let default_root = app_data.join("library");
            let preference_path = app_data.join("preferences.json");
            let location = settings::load_preference(&preference_path, &default_root)
                .unwrap_or_else(|_| settings::LibraryLocation::new(default_root.clone(), true));
            let library_root = location.root;
            paths::prepare_library(&library_root)
                .map_err(|error| format!("library initialization failed: {error:?}"))?;
            // Clean names before the engine or the UI can see the files.
            let playback_cache = app.path().app_local_data_dir()?.join("playback-cache");
            names::tidy_library(
                &library_root,
                Some(&playback_cache),
                &preference_path.with_file_name("renames.json"),
            );
            let network = settings::load_network(&preference_path);
            let audio_preference = settings::load_audio(&preference_path);
            let sidecar =
                sidecar::SidecarManager::start(app.handle().clone(), &library_root, &network)
                    .map_err(|error| format!("media engine startup failed: {error}"))?;
            app.manage(commands::AppState::new(
                sidecar.clone(),
                library_root,
                network,
                default_root,
                preference_path,
            ));
            // Playback preparation for videos the webview can't play as they are.
            let exe = std::env::current_exe()?;
            let suffix = if cfg!(windows) { ".exe" } else { "" };
            let tool = |name: &str| {
                sidecar::bundled_binary_sibling(&exe, &format!("{name}{suffix}"))
                    .unwrap_or_default()
            };
            app.manage(Arc::new(covers::CoverJobs::default()));
            // Private folder: the key lives only in memory; idle locks it.
            app.manage(Arc::new(vault_commands::VaultSession::default()));
            vault_commands::start_auto_lock(app.handle().clone());
            app.manage(subtitles::SubtitleCache(
                app.path().app_local_data_dir()?.join("subtitle-cache"),
            ));
            app.manage(Arc::new(durations::DurationCache::new(
                app.path().app_local_data_dir()?.join("durations.json"),
            )));
            let prepare_events = app.handle().clone();
            app.manage(Arc::new(preparer::Preparer::new(
                tool("ffmpeg"),
                tool("ffprobe"),
                playback_cache,
                Arc::new(move |payload| {
                    let _ = prepare_events.emit("playback-prepare", payload);
                }),
            )));
            // Loudness levelling: measured songs play at one level.
            let loudness = Arc::new(loudness::LoudnessCache::new(
                app.path().app_local_data_dir()?.join("loudness.json"),
            ));
            app.manage(Arc::clone(&loudness));
            let leveler: audio::engine::Leveler = Arc::new(move |song: &std::path::Path| {
                loudness.get(song).map(loudness::level_gain)
            });
            let events = app.handle().clone();
            let roots = app.handle().clone();
            app.manage(Arc::new(audio::service::AudioService::new(
                audio_preference,
                Arc::new(move |payload| {
                    let _ = events.emit("audio-event", payload);
                }),
                Arc::new(move || {
                    roots
                        .try_state::<commands::AppState>()
                        .and_then(|state| state.library_root().ok())
                }),
                leveler,
            )));
            let probe = sidecar;
            tauri::async_runtime::spawn(async move {
                let _ = probe.request("probe", serde_json::json!({})).await;
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::inspect_link,
            commands::start_download,
            commands::cancel_download,
            commands::list_library,
            commands::library_renames,
            commands::open_media,
            commands::open_library,
            commands::read_artwork,
            commands::delete_media,
            commands::read_lyrics,
            commands::read_track_info,
            commands::save_lyrics,
            commands::get_download_location,
            commands::choose_download_location,
            commands::use_default_download_location,
            commands::get_network_settings,
            commands::set_network_settings,
            commands::get_ytdlp_status,
            commands::update_ytdlp,
            commands::window_minimize,
            commands::window_toggle_maximize,
            commands::window_set_fullscreen,
            commands::prepare_playback,
            commands::import_media,
            commands::cancel_playback,
            commands::read_subtitles,
            vault_commands::vault_status,
            vault_commands::vault_create,
            vault_commands::vault_unlock,
            vault_commands::vault_lock,
            vault_commands::vault_change_password,
            vault_commands::vault_items,
            vault_commands::vault_cover,
            vault_commands::vault_restore,
            vault_commands::vault_delete,
            vault_commands::vault_add,
            commands::add_subtitles,
            commands::window_close,
            audio_commands::audio_play,
            audio_commands::audio_pause,
            audio_commands::audio_resume,
            audio_commands::audio_seek,
            audio_commands::audio_stop,
            audio_commands::audio_release,
            audio_commands::audio_set_volume,
            audio_commands::audio_set_next,
            audio_commands::audio_devices,
            audio_commands::audio_get_settings,
            audio_commands::audio_set_settings,
        ])
        .on_window_event(|window, event| {
            // Give the device back when the window goes (exclusive mode
            // would otherwise hold it until the process exits).
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(audio) = window.try_state::<Arc<audio::service::AudioService>>() {
                    audio.shutdown();
                }
                if let Some(preparer) = window.try_state::<Arc<preparer::Preparer>>() {
                    preparer.shutdown();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Qtmedia");
}
