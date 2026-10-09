pub mod commands;
pub mod paths;
pub mod protocol;
pub mod settings;
pub mod sidecar;

use tauri::Manager;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_opener::Builder::new()
                .open_js_links_on_click(false)
                .build(),
        )
        .setup(|app| {
            let app_data = app.path().app_data_dir()?.join("Qtmedia");
            let default_root = app_data.join("library");
            let preference_path = app_data.join("preferences.json");
            let location = settings::load_preference(&preference_path, &default_root)
                .unwrap_or_else(|_| settings::LibraryLocation::new(default_root.clone(), true));
            let library_root = location.root;
            paths::prepare_library(&library_root)
                .map_err(|error| format!("library initialization failed: {error:?}"))?;
            let sidecar = sidecar::SidecarManager::start(app.handle().clone(), &library_root)
                .map_err(|error| format!("media engine startup failed: {error}"))?;
            app.manage(commands::AppState::new(
                sidecar.clone(),
                library_root,
                default_root,
                preference_path,
            ));
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
            commands::get_download_location,
            commands::choose_download_location,
            commands::use_default_download_location,
            commands::window_minimize,
            commands::window_toggle_maximize,
            commands::window_close,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Qtmedia");
}
