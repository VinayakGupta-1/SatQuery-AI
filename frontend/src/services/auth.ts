/**
 * Session handling.
 *
 * ---------------------------------------------------------------------------
 * IMPORTANT: the SatQuery backend publishes no authentication endpoint.
 *
 * There is no `/api/auth/login`, no token issuer and no user model anywhere in
 * `backend/app`. Rather than pretend otherwise - posting credentials to an
 * endpoint that does not exist, or "verifying" a password in the browser,
 * which verifies nothing - this module defines the *interface* the application
 * uses for sessions and ships one honest implementation of it.
 *
 * `LocalSessionProvider` opens a workspace session on this device after
 * confirming the analysis service is actually reachable. It stores an operator
 * name and nothing else. A password, if one is typed, is never transmitted and
 * never stored.
 *
 * When the backend grows real authentication, implement `AuthProvider` against
 * it and swap the single `authProvider` export below. Nothing else in the
 * application needs to change: every consumer goes through `AuthContext`.
 * ---------------------------------------------------------------------------
 */

import { health } from './satquery'
import { ApiError } from './http'

export interface Session {
  /** Display name for the operator. Derived from what was entered at sign-in. */
  operator: string
  /** The identifier that was entered - an email or a callsign. */
  identifier: string
  /** ISO timestamp the session was opened. */
  openedAt: string
  /**
   * How this session was established. `local` means it was opened on this
   * device without a server-issued credential, because the backend does not
   * issue one. A future server-backed provider would report `server`.
   */
  origin: 'local' | 'server'
}

export interface Credentials {
  identifier: string
  password: string
  remember: boolean
}

export interface AuthProvider {
  /** Restore a persisted session, or null when there is none. */
  restore(): Session | null
  /** Open a session. Rejects with `AuthError` when it cannot be opened. */
  signIn(credentials: Credentials): Promise<Session>
  /** Discard the session. */
  signOut(): void
}

export class AuthError extends Error {
  /** Which field the message belongs against, when it belongs against one. */
  readonly field?: 'identifier' | 'password'

  constructor(message: string, field?: 'identifier' | 'password') {
    super(message)
    this.name = 'AuthError'
    this.field = field
  }
}

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
      origin: parsed.origin === 'server' ? 'server' : 'local',
    }
  } catch {
    return null
  }
}

/** Turn `a.mahajan@isro.gov.in` or `A Mahajan` into a display name. */
function operatorName(identifier: string): string {
  const stem = identifier.includes('@') ? identifier.split('@')[0] : identifier
  const parts = stem.split(/[._\-\s]+/).filter(Boolean)
  // Drop initials when there is a real name beside them, so
  // `a.mahajan` greets "Mahajan" rather than "A".
  const meaningful = parts.filter((part) => part.length > 1)
  const words = (meaningful.length > 0 ? meaningful : parts).map(
    (word) => word.charAt(0).toUpperCase() + word.slice(1),
  )
  return words.join(' ') || 'Operator'
}

class LocalSessionProvider implements AuthProvider {
  restore(): Session | null {
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

  signOut(): void {
    try {
      window.localStorage.removeItem(STORAGE_KEY)
      window.sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      // Nothing to clean up if storage is unavailable.
    }
  }
}

/** The provider the application uses. Swap this to move to server sessions. */
export const authProvider: AuthProvider = new LocalSessionProvider()
