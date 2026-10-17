import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EarthCanvas, type EarthHandle } from '../earth/EarthCanvas'
import { Wordmark } from '../../components/brand/Logo'
import { Button, Checkbox, TextField } from '../../components/ui'
import { useAuth } from '../../context/authContext'
import { useCapabilities } from '../../context/capabilitiesContext'
import { usePrefersReducedMotion } from '../../hooks/useMediaQuery'
import { AuthError, MIN_PASSWORD_LENGTH } from '../../services/auth'
import { launchVeil } from '../launch/launchStore'
import './login.css'

/** Length of the descent. Long enough to read as travel, short enough to sit
 *  through on a second sign-in. */
const DESCENT_MS = 1900

type Phase = 'form' | 'descending'

/** What the card is for. Only `signin` exists when the deployment has no accounts. */
type Mode = 'signin' | 'signup' | 'check-inbox'

interface FormError {
  message: string
  field?: string
  /** Offer to resend the verification email for this address. */
  resendTo?: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const {
    kind,
    session,
    recovering,
    signIn,
    signUp,
    signingIn,
    resendVerification,
    requestPasswordReset,
    updatePassword,
  } = useAuth()
  const { capabilities, loading: capabilitiesLoading, error: capabilitiesError } =
    useCapabilities()
  const reducedMotion = usePrefersReducedMotion()
  const accounts = kind === 'supabase'

  const earthRef = useRef<EarthHandle>(null)
  const skipRef = useRef<(() => void) | null>(null)

  const [mode, setMode] = useState<Mode>('signin')
  const [name, setName] = useState('')
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [phase, setPhase] = useState<Phase>('form')
  const [error, setError] = useState<FormError | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // The veil is cleared on arrival at the workspace; if this screen is left
  // some other way, clear it here too rather than leaving the app covered.
  useEffect(() => () => launchVeil.clear(), [])

  /** Hand over to the workspace: cover, navigate, uncover. */
  const enterWorkspace = useCallback(async () => {
    await launchVeil.cover()
    navigate('/', { replace: true })
    // One frame for the workspace to mount underneath before the veil lifts.
    window.requestAnimationFrame(() => {
      window.setTimeout(() => launchVeil.clear(), 60)
    })
  }, [navigate])

  const runDescent = useCallback(async () => {
    setPhase('descending')
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      skipRef.current = null
      void enterWorkspace()
    }
    // Escape, or a click anywhere, cuts the sequence short. A cinematic is
    // welcome once and tiresome on the fifth sign-in of a demo.
    skipRef.current = finish
    await earthRef.current?.descend(DESCENT_MS)
    finish()
  }, [enterWorkspace])

  // A session arriving by any route - the form, a verification link opened
  // from the inbox, a session restored on load - leads into the workspace.
  // A password-reset link opens a session too, but a new password comes first.
  useEffect(() => {
    if (session && !recovering && phase === 'form') void runDescent()
  }, [session, recovering, phase, runDescent])

  useEffect(() => {
    if (phase !== 'descending') return
    const skip = (event: KeyboardEvent | MouseEvent) => {
      if (event instanceof KeyboardEvent && event.key !== 'Escape' && event.key !== ' ') {
        return
      }
      skipRef.current?.()
    }
    window.addEventListener('keydown', skip)
    window.addEventListener('click', skip)
    return () => {
      window.removeEventListener('keydown', skip)
      window.removeEventListener('click', skip)
    }
  }, [phase])

  const fail = (cause: unknown, fallback: string) => {
    if (cause instanceof AuthError) {
      setError({
        message: cause.message,
        field: cause.field,
        resendTo: cause.code === 'unconfirmed' ? identifier.trim() : undefined,
      })
    } else {
      setError({ message: fallback })
    }
  }

  const submit = async () => {
    setError(null)
    setNotice(null)
    if (recovering) {
      setBusy(true)
      try {
        await updatePassword(password)
        setNotice('Password changed. Opening your workspace.')
      } catch (cause) {
        fail(cause, 'The password could not be changed.')
      } finally {
        setBusy(false)
      }
      return
    }
    if (mode === 'signup') {
      try {
        const opened = await signUp({ name, email: identifier, password })
        if (!opened) {
          setMode('check-inbox')
          setPassword('')
        }
      } catch (cause) {
        fail(cause, 'The account could not be created.')
      }
      return
    }
    try {
      await signIn({ identifier, password, remember })
    } catch (cause) {
      fail(cause, 'The session could not be opened.')
    }
  }

  const resend = async (email: string) => {
    setBusy(true)
    setError(null)
    try {
      await resendVerification(email)
      setNotice(`A new verification link is on its way to ${email}.`)
    } catch (cause) {
      fail(cause, 'The verification email could not be sent.')
    } finally {
      setBusy(false)
    }
  }

  const forgot = async () => {
    setError(null)
    setNotice(null)
    if (!accounts) {
      setError({ message: 'Passphrase recovery is handled by your deployment administrator.' })
      return
    }
    setBusy(true)
    try {
      await requestPasswordReset(identifier)
      setNotice(`If ${identifier.trim()} has an account, a reset link is on its way.`)
    } catch (cause) {
      fail(cause, 'The reset email could not be sent.')
    } finally {
      setBusy(false)
    }
  }

  const switchMode = (next: Mode) => {
    setMode(next)
    setError(null)
    setNotice(null)
  }

  const serviceStatus = capabilitiesLoading
    ? { tone: 'idle', text: 'Contacting analysis service' }
    : capabilitiesError
      ? { tone: 'down', text: 'Analysis service unreachable' }
      : {
          tone: 'up',
          text: `Analysis service online · ${capabilities?.executable.length ?? 0} capabilities ready`,
        }

  const heading = recovering
    ? 'Choose a new password'
    : mode === 'signup'
      ? 'Create your account'
      : mode === 'check-inbox'
        ? 'Check your inbox'
        : 'Open workspace'

  const working = signingIn || busy || phase === 'descending'

  return (
    <div className={`sq-login sq-login--${phase}`}>
      <div className="sq-login__stage">
        <EarthCanvas ref={earthRef} />
        {/* The reticle resolves over the surface as the camera arrives: the
            moment the globe stops being a view and becomes a workspace. */}
        <div className="sq-login__reticle" aria-hidden="true">
          <span className="sq-login__reticle-grid" />
          <span className="sq-login__reticle-sweep" />
        </div>
      </div>

      <header className="sq-login__brand">
        <Wordmark size="lg" tagline="Earth observation, asked in plain language" />
      </header>

      <main className="sq-login__panel" id="main">
        <form
          className="sq-login__card"
          onSubmit={(event) => {
            event.preventDefault()
            void submit()
          }}
          noValidate
        >
          <div className="sq-login__intro">
            <h1 className="sq-login__title">{heading}</h1>
            <p className="sq-login__subtitle">
              {recovering
                ? `At least ${MIN_PASSWORD_LENGTH} characters.`
                : mode === 'signup'
                  ? 'We will email you a link to verify your address before your first sign-in.'
                  : mode === 'check-inbox'
                    ? `We sent a verification link to ${identifier.trim()}. Open it to activate your account, then sign in here.`
                    : 'Sign in to query satellite imagery and review analysis results.'}
            </p>
          </div>

          {mode === 'check-inbox' && !recovering ? (
            <>
              {notice ? <p className="sq-login__notice" role="status">{notice}</p> : null}
              {error ? <p className="sq-login__error" role="alert">{error.message}</p> : null}
              <Button
                type="button"
                variant="primary"
                size="lg"
                block
                onClick={() => switchMode('signin')}
              >
                I have verified my email
              </Button>
              <Button
                type="button"
                variant="ghost"
                block
                disabled={busy}
                onClick={() => void resend(identifier.trim())}
              >
                Send the link again
              </Button>
            </>
          ) : (
            <>
              {mode === 'signup' && !recovering ? (
                <TextField
                  label="Name"
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  error={error?.field === 'name' ? error.message : null}
                  required
                />
              ) : null}

              {!recovering ? (
                <TextField
                  label={accounts ? 'Email' : 'Email or callsign'}
                  type={accounts ? 'email' : 'text'}
                  autoComplete={accounts ? 'email' : 'username'}
                  autoCapitalize="none"
                  spellCheck={false}
                  value={identifier}
                  onChange={(event) => setIdentifier(event.target.value)}
                  error={error?.field === 'identifier' ? error.message : null}
                  required
                />
              ) : null}

              <TextField
                label={recovering ? 'New password' : accounts ? 'Password' : 'Passphrase'}
                type="password"
                autoComplete={recovering || mode === 'signup' ? 'new-password' : 'current-password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                error={error?.field === 'password' ? error.message : null}
                hint={
                  recovering || mode === 'signup'
                    ? `At least ${MIN_PASSWORD_LENGTH} characters.`
                    : undefined
                }
                required
              />

              {error && (!error.field || error.resendTo) ? (
                <p className="sq-login__error" role="alert">
                  {error.field ? null : error.message}
                  {error.resendTo ? (
                    <button
                      type="button"
                      className="sq-login__inline"
                      disabled={busy}
                      onClick={() => void resend(error.resendTo!)}
                    >
                      Send the verification link again
                    </button>
                  ) : null}
                </p>
              ) : null}
              {notice ? (
                <p className="sq-login__notice" role="status">
                  {notice}
                </p>
              ) : null}

              {mode === 'signin' && !recovering ? (
                <div className="sq-login__row">
                  <Checkbox
                    label="Keep me signed in"
                    checked={remember}
                    onChange={(event) => setRemember(event.target.checked)}
                  />
                  <a
                    className="sq-login__link"
                    href="#recovery"
                    onClick={(event) => {
                      event.preventDefault()
                      void forgot()
                    }}
                  >
                    {accounts ? 'Forgot password?' : 'Forgot passphrase?'}
                  </a>
                </div>
              ) : null}

              <Button type="submit" variant="primary" size="lg" block disabled={working}>
                {phase === 'descending'
                  ? 'Entering workspace'
                  : recovering
                    ? busy
                      ? 'Saving'
                      : 'Save the new password'
                    : mode === 'signup'
                      ? signingIn
                        ? 'Creating account'
                        : 'Create account'
                      : signingIn
                        ? 'Opening session'
                        : 'Enter workspace'}
              </Button>

              {accounts && !recovering ? (
                <p className="sq-login__switch">
                  {mode === 'signup' ? 'Already have an account? ' : 'New to SatQuery? '}
                  <button
                    type="button"
                    className="sq-login__inline"
                    onClick={() => switchMode(mode === 'signup' ? 'signin' : 'signup')}
                  >
                    {mode === 'signup' ? 'Sign in' : 'Create an account'}
                  </button>
                </p>
              ) : null}
            </>
          )}

          <p className="sq-login__note">
            {accounts
              ? 'Accounts are managed by Supabase. Your password goes only to the account service, over TLS, and SatQuery never sees it.'
              : 'This deployment issues sessions locally. Your passphrase is not transmitted or stored.'}
          </p>
        </form>
      </main>

      <footer className="sq-login__status">
        <span className={`sq-login__dot sq-login__dot--${serviceStatus.tone}`} />
        <span>{serviceStatus.text}</span>
      </footer>

      {phase === 'descending' && !reducedMotion ? (
        <p className="sq-login__skip" aria-live="polite">
          Press Esc to skip
        </p>
      ) : null}

      <span className="sq-sr-only" aria-live="polite">
        {phase === 'descending' ? 'Signed in. Opening the workspace.' : ''}
      </span>
    </div>
  )
}

/** Route-level default export, so the page can be lazily loaded. */
export default LoginPage
