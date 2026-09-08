import { useSyncExternalStore } from 'react'

/**
 * Subscribe to a media query.
 *
 * `useSyncExternalStore` rather than an effect, so the very first render is
 * already correct - which matters for the sidebar, whose desktop and mobile
 * forms are structurally different and must not flash from one to the other.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/** Below this width the sidebar becomes a drawer. */
export const COMPACT_QUERY = '(max-width: 900px)'

export function useIsCompact(): boolean {
  return useMediaQuery(COMPACT_QUERY)
}

/**
 * Whether the operating system asks for reduced motion.
 *
 * Consulted by everything that moves for a reason other than showing progress:
 * the cinematic entry, the Earth's idle rotation, card entrances.
 */
export function usePrefersReducedMotion(): boolean {
  return useMediaQuery('(prefers-reduced-motion: reduce)')
}
