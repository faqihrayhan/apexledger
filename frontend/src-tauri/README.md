# ApexLedger Desktop (Tauri)

Wraps the ApexLedger web UI (React + Vite) into native desktop apps
for Windows (`.msi`), macOS (`.dmg`), and Linux (`.AppImage`).

## Prerequisites

- Node.js 18+ and npm (for the frontend build)
- Rust toolchain: install via <https://rustup.rs>
- Platform extras:
  - Windows: WebView2 (preinstalled on Windows 10/11)
  - macOS: Xcode Command Line Tools
  - Linux: `libwebkit2gtk-4.1-dev`, `build-essential`, `libssl-dev`

## Development

```bash
cd frontend
npm install
npm run tauri dev
```

(Add the `tauri` CLI once: `npm install -D @tauri-apps/cli`.)

## Build installers

```bash
npm run tauri build
```

Artifacts land in `frontend/src-tauri/target/release/bundle/`:

| Target | Output |
|---|---|
| Windows | `.msi` installer |
| macOS | `.dmg` disk image |
| Linux | `.AppImage` |

## Configuration

`tauri.conf.json` points at the Vite dev server (`:3000`) for
development and the static `../dist` folder for production builds.
The window uses the dark theme and a 1280x800 default size.

On first launch the UI asks: connect to a local ApexLedger server
(the factory machine, e.g. `http://192.168.1.100:8000`) or run
standalone. See the main README for server setup (`apexledger init`).
