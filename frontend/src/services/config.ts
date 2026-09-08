/**
 * Where the backend lives.
 *
 * In development the Vite dev server proxies `/api` to the FastAPI process, so
 * the base is empty and the browser stays same-origin. In a deployment where
 * the API is on another origin, set `VITE_API_BASE_URL` at build time and add
 * the frontend origin to the backend's `SATQUERY_CORS_ORIGINS`.
 */
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

/** Resolve a server-relative path (including artifact URLs) to a fetchable URL. */
export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}
