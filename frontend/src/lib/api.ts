/**
 * HTTP client for communicating with the FastAPI backend.
 *
 * Automatically injects the JWT token from the auth store and
 * normalizes error shapes (including the structured RPC error contract).
 */

import { useAuthStore } from "@/stores/auth";
import { apiBase } from "@/stores/server";

const API_PREFIX = "/api/v1";

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /**
   * Optional absolute server URL for this single request. Used by the
   * connect screen to probe a candidate factory server before the
   * server store is updated (persisting a URL that has never answered
   * would brick the app in "cannot connect" limbo).
   */
  probeUrl?: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(
      typeof detail === "string"
        ? detail
        : "An unexpected error occurred.",
    );
    this.name = "ApiError";
  }

  /** Structured message from the RPC error contract, if present. */
  get message2(): string | null {
    const d = this.detail as { message?: string; error_code?: string } | string;
    if (typeof d === "object" && d !== null && "message" in d) {
      return (d as { message?: string }).message ?? null;
    }
    return null;
  }

  /** Human-friendly error text for UI display. */
  get uiMessage(): string {
    return (
      this.message2 ??
      (typeof this.detail === "string" && this.detail
        ? this.detail
        : "Something went wrong. Please try again.")
    );
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, probeUrl, ...fetchOptions } = options;
  const base = probeUrl ?? apiBase();

  const headers = new Headers(fetchOptions.headers);
  headers.set("Content-Type", "application/json");

  const token = useAuthStore.getState().token;
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${base}${API_PREFIX}${path}`, {
    ...fetchOptions,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(response.status, payload?.detail ?? response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "GET" }),

  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "PATCH", body }),

  put: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "PUT", body }),

  delete: <T>(path: string, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "DELETE" }),
};
