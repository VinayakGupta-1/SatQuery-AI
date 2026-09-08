import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EarthCanvas, type EarthHandle } from '../earth/EarthCanvas'
import { Wordmark } from '../../components/brand/Logo'
import { Button, Checkbox, TextField } from '../../components/ui'
import { useAuth } from '../../context/authContext'
import { useCapabilities } from '../../context/capabilitiesContext'
import { usePrefersReducedMotion } from '../../hooks/useMediaQuery'
import { AuthError } from '../../services/auth'
import { launchVeil } from '../launch/launchStore'
import './login.css'

/** Length of the descent. Long enough to read as travel, short enough to sit
 *  through on a second sign-in. */
const DESCENT_MS = 1900

type Phase = 'form' | 'descending'

export function LoginPage() {
  const navigate = useNavigate()
  const { signIn, signingIn } = useAuth()
  const { capabilities, loading: capabilitiesLoading, error: capabilitiesError } =
    useCapabilities()
  const reducedMotion = usePrefersReducedMotion()

  const earthRef = useRef<EarthHandle>(null)
  const skipRef = useRef<(() => void) | null>(null)

  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [phase, setPhase] = useState<Phase>('form')
  const [error, setError] = useState<{ message: string; field?: string } | null>(null)

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

  const submit = async () => {
    setError(null)
    try {
      await signIn({ identifier, password, remember })
      void runDescent()
    } catch (cause) {
      if (cause instanceof AuthError) {
        setError({ message: cause.message, field: cause.field })
      } else {
        setError({ message: 'The session could not be opened.' })
      }
    }
  }

  const serviceStatus = capabilitiesLoading
    ? { tone: 'idle', text: 'Contacting analysis service' }
    : capabilitiesError
      ? { tone: 'down', text: 'Analysis service unreachable' }
      : {
          tone: 'up',
          text: `Analysis service online · ${capabilities?.executable.length ?? 0} capabilities ready`,
        }

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
            <h1 className="sq-login__title">Open workspace</h1>
            <p className="sq-login__subtitle">
              Sign in to query satellite imagery and review analysis results.
            </p>
          </div>

          <TextField
            label="Email or callsign"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            error={error?.field === 'identifier' ? error.message : null}
            required
          />

          <TextField
            label="Passphrase"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            error={error?.field === 'password' ? error.message : null}
            required
          />

          {error && !error.field ? (
            <p className="sq-login__error" role="alert">
              {error.message}
            </p>
          ) : null}

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
                setError({
                  message:
                    'Passphrase recovery is handled by your deployment administrator.',
                })
              }}
            >
              Forgot passphrase?
            </a>
          </div>

          <Button
            type="submit"
            variant="primary"
            size="lg"
            block
            disabled={signingIn || phase === 'descending'}
          >
            {phase === 'descending'
              ? 'Entering workspace'
              : signingIn
                ? 'Opening session'
                : 'Enter workspace'}
          </Button>

          <p className="sq-login__note">
            This deployment issues sessions locally. Your passphrase is not
            transmitted or stored.
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
