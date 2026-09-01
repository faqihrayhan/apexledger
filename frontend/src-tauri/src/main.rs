// ApexLedger desktop shell — Tauri v2 entry point.
//
// The web UI (React/Vite build output) runs inside the native window.
// On first launch the UI asks the user for the ApexLedger server
// address (the factory machine, e.g. http://192.168.1.100:8000);
// the choice is persisted client-side by the server store.

// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    apexledger_desktop_lib::run()
}
