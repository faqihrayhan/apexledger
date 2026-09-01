/**
 * Server store — the ApexLedger backend endpoint this client talks to.
 *
 * In the browser this is always the same origin (empty base → relative
 * paths through the Vite proxy / reverse proxy). In the Tauri desktop
 * app there is no backend on the app origin, so the user must point the
 * client at a factory server (e.g. `http://192.168.1.100:8000`) on the
 * connect screen; the choice is persisted so it survives restarts.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

/** localStorage key — also referenced by docs/SETUP.md. */
const STORAGE_KEY = "apexledger-server";

interface ServerState {
  /** '' = same-origin (browser mode); otherwise an absolute base URL. */
  baseUrl: string;
  /** Display label for the header chip, derived from baseUrl. */
  setBaseUrl: (url: string) => void;
}

function normalize(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  // Allow bare "host:port" by defaulting the scheme to http (LAN factory
  // servers in the PRD are plain http).
  return /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(trimmed) ? trimmed : `http://${trimmed}`;
}

export const useServerStore = create<ServerState>()(
  persist(
    (set) => ({
      baseUrl: "",
      setBaseUrl: (url) => set({ baseUrl: normalize(url) }),
    }),
    { name: STORAGE_KEY },
  ),
);

/** Absolute-or-relative root for every API call. '' → same-origin. */
export function apiBase(): string {
  return useServerStore.getState().baseUrl;
}
