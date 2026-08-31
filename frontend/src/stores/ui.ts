/**
 * UI navigation store — current page + AI sidebar state.
 *
 * A lightweight Zustand-based router. Sufficient for the SPA shell;
 * TanStack Router (typed deep links) can replace this later without
 * touching page components.
 */

import { create } from "zustand";

export type Page =
  | "dashboard"
  | "journals"
  | "journal-new"
  | "trial-balance"
  | "accounts";

interface UiState {
  page: Page;
  aiSidebarOpen: boolean;
  navigate: (page: Page) => void;
  toggleAiSidebar: () => void;
}

export const useUiStore = create<UiState>()((set) => ({
  page: "dashboard",
  aiSidebarOpen: false,
  navigate: (page) => set({ page }),
  toggleAiSidebar: () => set((s) => ({ aiSidebarOpen: !s.aiSidebarOpen })),
}));
