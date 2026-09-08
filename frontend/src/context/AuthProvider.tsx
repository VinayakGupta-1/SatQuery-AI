import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authProvider, type Credentials, type Session } from '../services/auth'
import { AuthContext, type AuthState } from './authContext'

/**
 * Holds the workspace session.
 *
 * The provider is deliberately thin: it owns state and delegates every
 * decision to `services/auth`, so replacing local sessions with server-issued
 * ones is a change in one module rather than a change in the component tree.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [restoring, setRestoring] = useState(true)
  const [signingIn, setSigningIn] = useState(false)

  useEffect(() => {
    setSession(authProvider.restore())
    setRestoring(false)
  }, [])

  const signIn = useCallback(async (credentials: Credentials) => {
    setSigningIn(true)
    try {
      const opened = await authProvider.signIn(credentials)
      setSession(opened)
      return opened
    } finally {
      setSigningIn(false)
    }
  }, [])

  const signOut = useCallback(() => {
    authProvider.signOut()
    setSession(null)
  }, [])

  const value = useMemo<AuthState>(
    () => ({ session, restoring, signingIn, signIn, signOut }),
    [session, restoring, signingIn, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
