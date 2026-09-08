import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../context/authContext'

/**
 * The route guard.
 *
 * While the session is being restored nothing is rendered: showing the sign-in
 * screen for a frame and then replacing it would be a worse experience than a
 * blank one, and the restore is synchronous in practice.
 */
export function RequireSession({ children }: { children: ReactNode }) {
  const { session, restoring } = useAuth()
  const location = useLocation()

  if (restoring) return <div className="sq-boot" aria-busy="true" />

  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
