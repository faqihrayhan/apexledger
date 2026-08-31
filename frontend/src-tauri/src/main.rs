// ApexLedger desktop shell — Tauri v2 entry point.
//
// The web UI (React/Vite build output) runs inside the native window.
// On startup the app asks the user whether to connect to a local
// ApexLedger server (factory) or run standalone.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
