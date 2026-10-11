pub mod audio;
pub mod audio_commands;
pub mod commands;
pub mod import;
pub mod lyrics;
pub mod media;
pub mod paths;
pub mod playback;
pub mod preparer;
pub mod protocol;
pub mod removal;
pub mod settings;
pub mod sidecar;

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
            let prepare_events = app.handle().clone();
            app.manage(Arc::new(preparer::Preparer::new(
                tool("ffmpeg"),
                tool("ffprobe"),
                app.path().app_local_data_dir()?.join("playback-cache"),
                Arc::new(move |payload| {
                    let _ = prepare_events.emit("playback-prepare", payload);
                }),
            )));
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
