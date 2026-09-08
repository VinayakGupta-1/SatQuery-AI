/**
 * The veil that carries the eye across the sign-in / workspace route change.
 *
 * A route change unmounts one tree and mounts another, which is a cut. The
 * descent must not end in a cut, so a single full-screen element - owned by
 * `App`, outside the router - fades up over the last moments of the descent,
 * survives the navigation, and fades away again over the workspace.
 *
 * It is a two-value store, so it is a module rather than a context: no
 * provider, no re-render of the router, and `LoginPage` can drive it without
 * knowing anything about what mounts next.
 */

export type VeilState = 'clear' | 'opaque'

const listeners = new Set<() => void>()
let state: VeilState = 'clear'

/** How long the veil takes to cover, and to clear again. */
export const VEIL_IN_MS = 420
export const VEIL_OUT_MS = 560

function emit(): void {
  for (const listener of listeners) listener()
}

export const launchVeil = {
  subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },

  get(): VeilState {
    return state
  },

  /** Fade the veil up. Resolves once it is fully covering. */
  cover(): Promise<void> {
    state = 'opaque'
    emit()
    return new Promise((resolve) => window.setTimeout(resolve, VEIL_IN_MS))
  },

  /** Fade the veil away. Safe to call when it is already clear. */
  clear(): void {
    if (state === 'clear') return
    state = 'clear'
    emit()
  },
}
