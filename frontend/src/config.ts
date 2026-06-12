// Dev (vite on :5173): talk to the local backend. Production build: the
// backend serves the frontend itself, so API calls are same-origin relative.
export const API_URL =
  import.meta.env.VITE_API_URL ??
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

export const SESSION_STORAGE_KEY = "lawagent_session";

// Fired when the server rejects the stored session token, so the app can
// fall back to the login screen from anywhere.
export const UNAUTHORIZED_EVENT = "lawagent-unauthorized";

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem(SESSION_STORAGE_KEY);
  const headers = new Headers(init.headers);
  if (token) headers.set("X-Session-Token", token);
  return fetch(`${API_URL}${path}`, { ...init, headers }).then((response) => {
    if (response.status === 401 && token) {
      localStorage.removeItem(SESSION_STORAGE_KEY);
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    return response;
  });
}
