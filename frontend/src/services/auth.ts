/**
 * Session handling.
 *
 * Two providers implement one interface, and the backend decides which runs:
 *
 * `SupabaseSessionProvider` - when `/api/capabilities` carries an `auth`
 * block. Accounts live in the deployment's Supabase project: people sign up
 * with an email and a password, confirm the address from the email Supabase
 * sends, and sign in. Every API request then carries the user's access token,
 * which the backend verifies; results are stored per user.
 *
 * `LocalSessionProvider` - when the backend is open (no Supabase configured).
 * It opens a workspace session on this device after confirming the analysis
 * service is reachable, and stores an operator name and nothing else. A
 * password, if one is typed, is never transmitted and never stored.
 *
 * Every consumer goes through `AuthContext`, so nothing else in the
 * application knows which one is running.
 */

import {
  createClient,
  type AuthError as SupabaseAuthError,
  type Session as SupabaseSession,
  type SupabaseClient,
} from '@supabase/supabase-js'
import { health } from './satquery'
import { ApiError } from './http'
import type { AuthInfo } from '../types/api'

export interface Session {
  /** Display name for the operator. */
  operator: string
  /** The email address (or, locally, the callsign) the user signed in with. */
  identifier: string
  /** ISO timestamp the session was opened. */
  openedAt: string
  /** `server` when an account service issued the session, `local` otherwise. */
  origin: 'local' | 'server'
}

export interface Credentials {
  identifier: string
  password: string
  remember: boolean
}

export interface SignUpRequest {
  name: string
  email: string
  password: string
}

export type AuthEvent =
  | { type: 'signed-in'; session: Session }
  | { type: 'signed-out' }
  /** The user arrived from a password-reset email and must choose a new one. */
  | { type: 'password-recovery'; session: Session }

export interface AuthProvider {
  readonly kind: 'local' | 'supabase'
  /** Restore a persisted session, or null when there is none. */
  restore(): Promise<Session | null>
  /** Open a session. Rejects with `AuthError` when it cannot be opened. */
  signIn(credentials: Credentials): Promise<Session>
  /** Create an account. Resolves with a session only when no email
   *  confirmation is required; otherwise with `null`. */
  signUp(request: SignUpRequest): Promise<Session | null>
  resendVerification(email: string): Promise<void>
  requestPasswordReset(email: string): Promise<void>
  updatePassword(password: string): Promise<void>
  /** Discard the session. */
  signOut(): Promise<void>
  /** The token API requests carry, or null when there is none. */
  accessToken(): Promise<string | null>
  /** Changes the provider learns about by itself: a token refresh, a
   *  verification or reset link opened, a sign-out in another tab. */
  subscribe(listener: (event: AuthEvent) => void): () => void
}

export type AuthErrorCode = 'unconfirmed' | 'credentials' | 'exists' | 'weak' | 'other'

export class AuthError extends Error {
  /** Which field the message belongs against, when it belongs against one. */
  readonly field?: 'identifier' | 'password' | 'name'
  readonly code: AuthErrorCode

  constructor(message: string, field?: AuthError['field'], code: AuthErrorCode = 'other') {
    super(message)
    this.name = 'AuthError'
    this.field = field
    this.code = code
  }
}

/** Turn `a.mahajan@isro.gov.in` or `A Mahajan` into a display name. */
export function operatorName(identifier: string): string {
  const stem = identifier.includes('@') ? identifier.split('@')[0] : identifier
  const parts = stem.split(/[._\-\s+]+/).filter(Boolean)
  // Drop initials when there is a real name beside them, so
  // `a.mahajan` greets "Mahajan" rather than "A".
  const meaningful = parts.filter((part) => part.length > 1)
  const words = (meaningful.length > 0 ? meaningful : parts).map(
    (word) => word.charAt(0).toUpperCase() + word.slice(1),
  )
  return words.join(' ') || 'Operator'
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
export const MIN_PASSWORD_LENGTH = 8

/* ========================================================================== */
/* Local sessions                                                             */
/* ========================================================================== */

const STORAGE_KEY = 'satquery.session'

function readStored(store: Storage): Session | null {
  try {
    const raw = store.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Session>
    if (typeof parsed?.identifier !== 'string' || typeof parsed?.operator !== 'string') {
      return null
    }
    return {
      operator: parsed.operator,
      identifier: parsed.identifier,
      openedAt: parsed.openedAt ?? new Date().toISOString(),
      origin: 'local',
    }
  } catch {
    return null
  }
}

const NO_ACCOUNTS = 'This deployment has no accounts: sign in with any name.'

class LocalSessionProvider implements AuthProvider {
  readonly kind = 'local' as const

  async restore(): Promise<Session | null> {
    // A "remembered" session lives in localStorage; an unremembered one lives
    // in sessionStorage and ends with the tab.
    return readStored(window.localStorage) ?? readStored(window.sessionStorage)
  }

  async signIn(credentials: Credentials): Promise<Session> {
    const identifier = credentials.identifier.trim()
    if (!identifier) {
      throw new AuthError('Enter an email address or callsign.', 'identifier')
    }
    if (!credentials.password) {
      throw new AuthError('Enter a passphrase.', 'password')
    }

    // The one check that is real: the analysis service has to be there, or the
    // workspace behind this screen cannot do anything at all.
    try {
      const status = await health()
      if (status.status !== 'ok') {
        throw new AuthError('The analysis service is not reporting healthy.')
      }
    } catch (error) {
      if (error instanceof AuthError) throw error
      if (error instanceof ApiError) throw new AuthError(error.message)
      throw new AuthError('The analysis service could not be reached.')
    }

    const session: Session = {
      operator: operatorName(identifier),
      identifier,
      openedAt: new Date().toISOString(),
      origin: 'local',
    }

    const store = credentials.remember ? window.localStorage : window.sessionStorage
    try {
      // Deliberate: the passphrase is not part of this object and is discarded
      // the moment this function returns.
      store.setItem(STORAGE_KEY, JSON.stringify(session))
    } catch {
      // Private browsing with storage disabled. The session still holds for
      // this page lifetime; it simply will not survive a reload.
    }
    return session
  }

  async signUp(): Promise<Session | null> {
    throw new AuthError(NO_ACCOUNTS)
  }

  async resendVerification(): Promise<void> {
    throw new AuthError(NO_ACCOUNTS)
  }

  async requestPasswordReset(): Promise<void> {
    throw new AuthError(NO_ACCOUNTS)
  }

  async updatePassword(): Promise<void> {
    throw new AuthError(NO_ACCOUNTS)
  }

  async signOut(): Promise<void> {
    try {
      window.localStorage.removeItem(STORAGE_KEY)
      window.sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      // Nothing to clean up if storage is unavailable.
    }
  }

  async accessToken(): Promise<string | null> {
    return null
  }

  subscribe(): () => void {
    return () => {}
  }
}

/* ========================================================================== */
/* Supabase accounts                                                          */
/* ========================================================================== */

/** "Keep me signed in" decides where Supabase keeps the session. */
let remember = true

function safely<T>(action: () => T, fallback: T): T {
  try {
    return action()
  } catch {
    return fallback
  }
}

const sessionStore = {
  getItem: (key: string) =>
    safely(() => window.localStorage.getItem(key) ?? window.sessionStorage.getItem(key), null),
  setItem: (key: string, value: string) =>
    safely(() => {
      const [keep, drop] = remember
        ? [window.localStorage, window.sessionStorage]
        : [window.sessionStorage, window.localStorage]
      keep.setItem(key, value)
      drop.removeItem(key)
    }, undefined),
  removeItem: (key: string) =>
    safely(() => {
      window.localStorage.removeItem(key)
      window.sessionStorage.removeItem(key)
    }, undefined),
}

/** Where links in verification and reset emails bring the user back to. */
function returnUrl(): string {
  return `${window.location.origin}/login`
}

function toSession(session: SupabaseSession): Session {
  const email = session.user.email ?? ''
  const name = session.user.user_metadata?.full_name
  return {
    operator: typeof name === 'string' && name.trim() ? name.trim() : operatorName(email),
    identifier: email,
    openedAt: new Date().toISOString(),
    origin: 'server',
  }
}

/** Supabase's errors, said the way a person signing in needs to hear them. */
function explain(error: SupabaseAuthError, email = ''): AuthError {
  const code = (error as { code?: string }).code ?? ''
  const message = error.message ?? ''
  if (code === 'email_not_confirmed' || /not confirmed/i.test(message)) {
    return new AuthError(
      `Confirm your email address first: open the link sent to ${email || 'your inbox'}.`,
      'identifier',
      'unconfirmed',
    )
  }
  if (code === 'invalid_credentials' || /invalid login credentials/i.test(message)) {
    return new AuthError('The email address or password is incorrect.', 'password', 'credentials')
  }
  if (code === 'user_already_exists' || /already registered/i.test(message)) {
    return new AuthError('An account with this email already exists. Sign in instead.', 'identifier', 'exists')
  }
  if (code === 'weak_password' || /password/i.test(message)) {
    return new AuthError(message || 'Choose a stronger password.', 'password', 'weak')
  }
  if (code === 'over_email_send_rate_limit' || /rate limit/i.test(message)) {
    return new AuthError('Too many emails were sent just now. Wait a minute and try again.')
  }
  return new AuthError(message || 'The account service could not complete that.')
}

class SupabaseSessionProvider implements AuthProvider {
  readonly kind = 'supabase' as const
  private readonly client: SupabaseClient

  constructor(config: AuthInfo) {
    this.client = createClient(config.url, config.publishable_key, {
      auth: {
        storage: sessionStore,
        persistSession: true,
        autoRefreshToken: true,
        // Verification and reset links land on /login with the session in
        // the URL; the client picks it up from there.
        detectSessionInUrl: true,
        flowType: 'implicit',
      },
    })
  }

  async restore(): Promise<Session | null> {
    const { data } = await this.client.auth.getSession()
    return data.session ? toSession(data.session) : null
  }

  async signIn(credentials: Credentials): Promise<Session> {
    const email = credentials.identifier.trim()
    if (!EMAIL.test(email)) throw new AuthError('Enter your email address.', 'identifier')
    if (!credentials.password) throw new AuthError('Enter your password.', 'password')
    remember = credentials.remember
    const { data, error } = await this.client.auth.signInWithPassword({
      email,
      password: credentials.password,
    })
    if (error) throw explain(error, email)
    if (!data.session) throw new AuthError('The account service did not open a session.')
    return toSession(data.session)
  }

  async signUp(request: SignUpRequest): Promise<Session | null> {
    const email = request.email.trim()
    if (!request.name.trim()) throw new AuthError('Enter your name.', 'name')
    if (!EMAIL.test(email)) throw new AuthError('Enter a valid email address.', 'identifier')
    if (request.password.length < MIN_PASSWORD_LENGTH) {
      throw new AuthError(
        `Use at least ${MIN_PASSWORD_LENGTH} characters for your password.`,
        'password',
        'weak',
      )
    }
    const { data, error } = await this.client.auth.signUp({
      email,
      password: request.password,
      options: { emailRedirectTo: returnUrl(), data: { full_name: request.name.trim() } },
    })
    if (error) throw explain(error, email)
    // Supabase answers a sign-up for an existing address with a user that has
    // no identities, so as not to reveal which addresses have accounts.
    if (data.user && data.user.identities && data.user.identities.length === 0) {
      throw new AuthError(
        'An account with this email already exists. Sign in instead.',
        'identifier',
        'exists',
      )
    }
    return data.session ? toSession(data.session) : null
  }

  async resendVerification(email: string): Promise<void> {
    const { error } = await this.client.auth.resend({
      type: 'signup',
      email: email.trim(),
      options: { emailRedirectTo: returnUrl() },
    })
    if (error) throw explain(error, email)
  }

  async requestPasswordReset(email: string): Promise<void> {
    if (!EMAIL.test(email.trim())) {
      throw new AuthError('Enter your email address first.', 'identifier')
    }
    const { error } = await this.client.auth.resetPasswordForEmail(email.trim(), {
      redirectTo: returnUrl(),
    })
    if (error) throw explain(error, email)
  }

  async updatePassword(password: string): Promise<void> {
    if (password.length < MIN_PASSWORD_LENGTH) {
      throw new AuthError(
        `Use at least ${MIN_PASSWORD_LENGTH} characters for your password.`,
        'password',
        'weak',
      )
    }
    const { error } = await this.client.auth.updateUser({ password })
    if (error) throw explain(error)
  }

  async signOut(): Promise<void> {
    await this.client.auth.signOut().catch(() => undefined)
  }

  async accessToken(): Promise<string | null> {
    const { data } = await this.client.auth.getSession()
    return data.session?.access_token ?? null
  }

  subscribe(listener: (event: AuthEvent) => void): () => void {
    const { data } = this.client.auth.onAuthStateChange((event, session) => {
      // Only translate here: calling back into the client from inside this
      // callback can deadlock it.
      if (event === 'PASSWORD_RECOVERY' && session) {
        listener({ type: 'password-recovery', session: toSession(session) })
      } else if (event === 'SIGNED_OUT') {
        listener({ type: 'signed-out' })
      } else if (session && (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED' || event === 'USER_UPDATED')) {
        listener({ type: 'signed-in', session: toSession(session) })
      }
    })
    return () => data.subscription.unsubscribe()
  }
}

/** The provider for this deployment: accounts when the backend has them. */
export function createAuthProvider(config: AuthInfo | null | undefined): AuthProvider {
  return config ? new SupabaseSessionProvider(config) : new LocalSessionProvider()
}
