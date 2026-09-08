import { createContext, useContext } from 'react'
import type { Credentials, Session } from '../services/auth'

export interface AuthState {
  session: Session | null
  /** True while the initial restore is in flight. */
  restoring: boolean
  /** True while a sign-in attempt is in flight. */
  signingIn: boolean
  signIn: (credentials: Credentials) => Promise<Session>
  signOut: () => void
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>.')
  return value
}
