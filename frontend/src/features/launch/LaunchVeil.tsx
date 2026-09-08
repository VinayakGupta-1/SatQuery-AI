import { useSyncExternalStore } from 'react'
import { launchVeil } from './launchStore'
import './launch.css'

/**
 * The full-screen element the descent hands over to.
 *
 * Rendered once by `App`, above the router, so it is unaffected by the
 * navigation happening underneath it.
 */
export function LaunchVeil() {
  const state = useSyncExternalStore(
    launchVeil.subscribe,
    launchVeil.get,
    () => 'clear' as const,
  )

  return (
    <div
      className={`sq-veil${state === 'opaque' ? ' sq-veil--opaque' : ''}`}
      aria-hidden="true"
    />
  )
}
