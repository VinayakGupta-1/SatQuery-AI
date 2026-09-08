import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Wordmark } from '../../components/brand/Logo'
import { IconButton } from '../../components/ui'
import { LogoutIcon, MenuIcon, RefreshIcon } from '../../components/icons'
import { useAuth } from '../../context/authContext'
import { useCapabilities } from '../../context/capabilitiesContext'

interface TopBarProps {
  compact: boolean
  onOpenNavigation: () => void
}

/**
 * The one persistent chrome element.
 *
 * It carries the brand, the state of the analysis service, and the session.
 * Deliberately not a toolbar: no analysis control lives here, because the
 * controls belong beside the thing they act on.
 */
export function TopBar({ compact, onOpenNavigation }: TopBarProps) {
  const navigate = useNavigate()
  const { session, signOut } = useAuth()
  const { capabilities, loading, error, reload } = useCapabilities()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

  const status = loading
    ? { tone: 'idle', label: 'Connecting' }
    : error
      ? { tone: 'down', label: 'Service offline' }
      : {
          tone: 'up',
          label: `${capabilities?.executable.length ?? 0} capabilities online`,
        }

  const initials = (session?.operator ?? 'Operator')
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join('')

  return (
    <header className="sq-topbar">
      {compact ? (
        <IconButton
          label="Open navigation"
          onClick={onOpenNavigation}
          aria-controls="sq-sidebar"
        >
          <MenuIcon size={18} />
        </IconButton>
      ) : null}

      <Wordmark />

      <div className="sq-topbar__spacer" />

      <div className={`sq-topbar__status sq-topbar__status--${status.tone}`}>
        <span className="sq-topbar__dot" aria-hidden="true" />
        <span className="sq-topbar__status-text">{status.label}</span>
        {error ? (
          <IconButton label="Retry connection" size="sm" onClick={reload}>
            <RefreshIcon size={13} />
          </IconButton>
        ) : null}
      </div>

      <div className="sq-topbar__account" ref={menuRef}>
        <button
          type="button"
          className="sq-topbar__avatar"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((value) => !value)}
        >
          <span aria-hidden="true">{initials}</span>
          <span className="sq-sr-only">Session menu for {session?.operator}</span>
        </button>

        {menuOpen ? (
          <div className="sq-menu" role="menu">
            <div className="sq-menu__head">
              <span className="sq-menu__name">{session?.operator}</span>
              <span className="sq-menu__detail">{session?.identifier}</span>
            </div>
            <button
              type="button"
              role="menuitem"
              className="sq-menu__item"
              onClick={() => {
                setMenuOpen(false)
                signOut()
                navigate('/login', { replace: true })
              }}
            >
              <LogoutIcon size={15} />
              Sign out
            </button>
          </div>
        ) : null}
      </div>
    </header>
  )
}
