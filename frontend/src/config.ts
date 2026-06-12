// Dev (vite on :5173): talk to the local backend. Production build: the
// backend serves the frontend itself, so API calls are same-origin relative.
export const API_URL =
  import.meta.env.VITE_API_URL ??
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");
