//! ApexLedger desktop shell — library crate (Tauri v2).
//!
//! The binary entry (`main.rs`) is a thin wrapper around `run()` so the
//! shell can also be built as a mobile/library target later.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
