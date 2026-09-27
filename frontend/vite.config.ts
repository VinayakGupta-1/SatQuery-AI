import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * The dev server proxies `/api` (and the `/health` and `/analyze` aliases) to
 * the FastAPI backend. That keeps the browser same-origin in development, so the artifact
 * URLs the backend returns (`/api/tasks/<id>/artifacts/<id>`) can be used
 * verbatim and CORS never enters the picture.
 *
 * Set VITE_API_BASE_URL for a deployment where the API lives elsewhere; the
 * backend's SATQUERY_CORS_ORIGINS must then list the frontend origin.
 */
const BACKEND = process.env.VITE_DEV_BACKEND ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
      '/analyze': { target: BACKEND, changeOrigin: true },
      // Not '/capabilities' or '/results': those are the app's own pages
      // (/capabilities, /results/:taskId), and proxying them served the
      // backend's JSON on a reload or an opened link. The app reads both
      // through /api.
    },
  },
  build: {
    target: 'es2022',
    rollupOptions: {
      output: {
        // three.js and the GeoTIFF decoder are only needed on specific screens;
        // splitting them keeps the initial workspace payload small.
        manualChunks: {
          three: ['three'],
          geotiff: ['geotiff'],
        },
      },
    },
  },
})
