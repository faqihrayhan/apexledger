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

Prefer the GitHub Actions workflow (`.github/workflows/desktop.yml`,
manual dispatch) when the local machine has no Rust toolchain — it
builds the same installers on hosted runners and attaches them to the
workflow run.

## Configuration

`tauri.conf.json` points at the Vite dev server (`:3000`) for
development and the static `../dist` folder for production builds.
The window uses the dark theme and a 1280x800 default size.

On first launch the UI asks for the ApexLedger server address (the
factory machine, e.g. `http://192.168.1.100:8000`); the choice is
persisted in the app's localStorage (`apexledger-server`) and can be
changed any time from the header chip. See the main README for server
setup (`apexledger init`).

## Layout

```
src-tauri/
├── build.rs          # tauri_build — embeds config/icons into the binary
├── Cargo.toml        # crate manifest (lib + bin)
├── capabilities/     # Tauri v2 ACL — core:default only
├── icons/            # generated icon set (png/ico/icns)
├── src/
│   ├── lib.rs        # run() — the builder, shared by all targets
│   └── main.rs       # desktop binary entry
└── tauri.conf.json   # window + bundler config
```
