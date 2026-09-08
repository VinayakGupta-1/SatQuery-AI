/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute base URL of the SatQuery backend. Empty in development, where
   *  the Vite dev server proxies the API. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** TopoJSON data shipped by `world-atlas`, imported with resolveJsonModule. */
declare module 'world-atlas/land-110m.json' {
  const topology: unknown
  export default topology
}
