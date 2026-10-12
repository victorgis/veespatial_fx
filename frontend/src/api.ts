import type { Dashboard, Market, Me, Settings, Signal } from "./types";

const TOKEN_KEY = "signaldesk.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    setToken(null);
    throw new ApiError("Sign in again.");
  }
  if (!response.ok) {
    let message = "Something went wrong. Try again.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0] && typeof body.detail[0] === "object" && "msg" in body.detail[0]) {
        message = String((body.detail[0] as { msg: string }).msg);
      }
    } catch {
      /* keep the fallback */
    }
    throw new ApiError(message);
  }
  return (await response.json()) as T;
}

export const desk = {
  register: (email: string, name: string, password: string) =>
    api<{ token: string }>("/api/auth/register", { method: "POST", body: JSON.stringify({ email, name, password }) }),
  login: (email: string, password: string) =>
    api<{ token: string }>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => api<Me>("/api/me"),
  dashboard: () => api<Dashboard>("/api/dashboard"),
  markets: () => api<Market[]>("/api/markets"),
  signals: () => api<Signal[]>("/api/signals"),
  signal: (id: number) => api<Signal>(`/api/signals/${id}`),
  mark: (id: number, action: "you_placed" | "you_skipped") =>
    api<Signal>(`/api/signals/${id}/mark`, { method: "POST", body: JSON.stringify({ action }) }),
  saveSettings: (settings: Omit<Settings, "ea_key_prefix">) =>
    api<{ settings: Settings; ea_key: string | null }>("/api/settings", { method: "PUT", body: JSON.stringify(settings) }),
  rotateKey: () => api<{ ea_key: string; ea_key_prefix: string }>("/api/settings/ea-key", { method: "POST" }),
  saveWatchlist: (enabled_symbols: string[]) =>
    api<{ enabled_symbols: string[] }>("/api/system/watchlist", {
      method: "PUT",
      body: JSON.stringify({ enabled_symbols }),
    }),
  scan: () => api<{ status: string; message: string; signals_created: number }>("/api/system/scan", { method: "POST" }),
};
