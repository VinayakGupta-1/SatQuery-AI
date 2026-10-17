import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  createAuthProvider,
  type AuthProvider as SessionProvider,
  type Credentials,
  type Session,
  type SignUpRequest,
} from '../services/auth'
import { configureAuth } from '../services/http'
import { useCapabilities } from './capabilitiesContext'
import { AuthContext, type AuthState } from './authContext'

/**
 * Holds the workspace session.
 *
 * Which kind of session depends on the deployment, and only the analysis
 * service knows that: `/api/capabilities` carries an `auth` block when users
 * must have accounts. So this waits for the capabilities, picks the provider,
 * restores any session, and hands the provider's access token to the HTTP
 * layer so every API call is made as the signed-in user.
 *
 * Every decision about credentials stays in `services/auth`; this component
 * only owns state.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const { capabilities, error: serviceError } = useCapabilities()
  const [session, setSession] = useState<Session | null>(null)
  const [restoring, setRestoring] = useState(true)
  const [signingIn, setSigningIn] = useState(false)
  const [recovering, setRecovering] = useState(false)

  // Keyed on the configuration, not the capabilities object, so a refresh of
  // the capabilities does not tear down a signed-in client.
  const authUrl = capabilities?.auth?.url ?? null
  const authKey = capabilities?.auth?.publishable_key ?? null
  const known = capabilities !== null || serviceError !== null
  const provider = useMemo<SessionProvider | null>(() => {
    if (!known) return null
    return createAuthProvider(authUrl && authKey ? { provider: 'supabase', url: authUrl, publishable_key: authKey, email_verification: true } : null)
  }, [known, authUrl, authKey])

  useEffect(() => {
    if (!provider) return
    let active = true
    configureAuth({
      accessToken: () => provider.accessToken(),
      // The backend no longer accepts the token: the session has ended.
      onUnauthorized: () => {
        void provider.signOut()
        setSession(null)
      },
    })
    const unsubscribe = provider.subscribe((event) => {
      if (!active) return
      if (event.type === 'signed-out') {
        setSession(null)
        setRecovering(false)
      } else {
        setSession(event.session)
        setRecovering(event.type === 'password-recovery')
      }
    })
    provider
      .restore()
      .then((restored) => {
        if (active) setSession(restored)
      })
      .catch(() => {
        if (active) setSession(null)
      })
      .finally(() => {
        if (active) setRestoring(false)
      })
    return () => {
      active = false
      unsubscribe()
      configureAuth(null)
    }
  }, [provider])

  const require = useCallback((): SessionProvider => {
    if (!provider) throw new Error('The analysis service has not said how to sign in yet.')
    return provider
  }, [provider])

  const signIn = useCallback(
    async (credentials: Credentials) => {
      setSigningIn(true)
      try {
        const opened = await require().signIn(credentials)
        setSession(opened)
        return opened
      } finally {
        setSigningIn(false)
      }
    },
    [require],
  )

  const signUp = useCallback(
    async (request: SignUpRequest) => {
      setSigningIn(true)
      try {
        const opened = await require().signUp(request)
        if (opened) setSession(opened)
        return opened
      } finally {
        setSigningIn(false)
      }
    },
    [require],
  )

  const resendVerification = useCallback(
    (email: string) => require().resendVerification(email),
    [require],
  )
  const requestPasswordReset = useCallback(
    (email: string) => require().requestPasswordReset(email),
    [require],
  )
  const updatePassword = useCallback(
    async (password: string) => {
      await require().updatePassword(password)
      setRecovering(false)
    },
    [require],
  )

  const signOut = useCallback(() => {
    void provider?.signOut()
    setSession(null)
    setRecovering(false)
  }, [provider])

  const value = useMemo<AuthState>(
    () => ({
      kind: provider?.kind ?? null,
      session,
      restoring: restoring || provider === null,
      signingIn,
      recovering,
      signIn,
      signUp,
      resendVerification,
      requestPasswordReset,
      updatePassword,
      signOut,
    }),
    [
      provider,
      session,
      restoring,
      signingIn,
      recovering,
      signIn,
      signUp,
      resendVerification,
      requestPasswordReset,
      updatePassword,
      signOut,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
