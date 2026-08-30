/**
 * Auth store — manages JWT token and user state.
 *
 * Persists the token in localStorage so sessions survive page reloads.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  userId: string | null;
  entityId: string | null;
  role: string | null;

  setAuth: (data: {
    token: string;
    userId: string;
    entityId?: string;
    role: string;
  }) => void;
  logout: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      userId: null,
      entityId: null,
      role: null,

      setAuth: (data) =>
        set({
          token: data.token,
          userId: data.userId,
          entityId: data.entityId ?? null,
          role: data.role,
        }),

      logout: () =>
        set({
          token: null,
          userId: null,
          entityId: null,
          role: null,
        }),

      isAuthenticated: () => get().token !== null,
    }),
    { name: "apexledger-auth" },
  ),
);
