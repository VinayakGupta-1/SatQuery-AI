import { createContext, useContext } from 'react'
import type { Credentials, Session, SignUpRequest } from '../services/auth'

export interface AuthState {
  /** `supabase` when the deployment has accounts; `local` when it is open;
   *  `null` until the analysis service has said which. */
  kind: 'local' | 'supabase' | null
  session: Session | null
  /** True while the initial restore is in flight. */
  restoring: boolean
  /** True while a sign-in attempt is in flight. */
  signingIn: boolean
  /** True after a password-reset link was opened: a new password is due. */
  recovering: boolean
  signIn: (credentials: Credentials) => Promise<Session>
  /** Resolves with a session only when no email confirmation is needed. */
  signUp: (request: SignUpRequest) => Promise<Session | null>
  resendVerification: (email: string) => Promise<void>
  requestPasswordReset: (email: string) => Promise<void>
  updatePassword: (password: string) => Promise<void>
  signOut: () => void
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>.')
  return value
}
