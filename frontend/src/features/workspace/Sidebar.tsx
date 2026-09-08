import { useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { NAVIGATION } from './navigation'
import { CloseIcon, CollapseIcon } from '../../components/icons'
import { IconButton, Tooltip } from '../../components/ui'
import { Wordmark } from '../../components/brand/Logo'

interface SidebarProps {
  /** Desktop: the rail is narrowed to icons only. */
  collapsed: boolean
  onToggleCollapsed: () => void
  /** Compact: the sidebar is a drawer over the content. */
  compact: boolean
  open: boolean
  onClose: () => void
}

/**
 * Navigation, and only navigation.
 *
 * The sidebar is a quiet surface: one weight of type, one accent, no counts,
 * no badges. Its job is to say where things are, not to compete with the
 * workspace for attention.
 */
export function Sidebar({
  collapsed,
  onToggleCollapsed,
  compact,
  open,
  onClose,
}: SidebarProps) {
  const asideRef = useRef<HTMLElement | null>(null)
  const showLabels = compact || !collapsed

  // As a drawer the sidebar is modal: Escape closes it, and focus moves into
  // it so a keyboard user is not left behind on the page underneath.
  useEffect(() => {
    if (!compact || !open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    asideRef.current?.querySelector<HTMLElement>('a, button')?.focus()
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [compact, open, onClose])

  return (
    <>
      {compact ? (
        <div
          className={`sq-scrim${open ? ' sq-scrim--open' : ''}`}
          onClick={onClose}
          aria-hidden="true"
        />
      ) : null}

      <aside
        ref={asideRef}
        id="sq-sidebar"
        className={[
          'sq-sidebar',
          collapsed && !compact ? 'sq-sidebar--collapsed' : '',
          compact ? 'sq-sidebar--drawer' : '',
          compact && open ? 'sq-sidebar--open' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        aria-label="Workspace sections"
        /* A closed drawer is still in the DOM for the slide transition, so it
           is made inert: no focus stop, no screen-reader content. */
        inert={compact && !open}
      >
        {compact ? (
          <div className="sq-sidebar__drawer-head">
            <Wordmark />
            <IconButton label="Close navigation" onClick={onClose}>
              <CloseIcon size={16} />
            </IconButton>
          </div>
        ) : null}

        <nav className="sq-sidebar__nav">
          {NAVIGATION.map((group) => (
            <div className="sq-sidebar__group" key={group.id}>
              {showLabels ? (
                <h2 className="sq-sidebar__group-label sq-label">{group.label}</h2>
              ) : (
                <span className="sq-sidebar__rule" aria-hidden="true" />
              )}
              <ul className="sq-sidebar__list">
                {group.items.map((item) => {
                  const Glyph = item.icon
                  const link = (
                    <NavLink
                      to={item.to}
                      end={item.end}
                      className={({ isActive }) =>
                        `sq-sidebar__link${isActive ? ' sq-sidebar__link--active' : ''}`
                      }
                      onClick={compact ? onClose : undefined}
                    >
                      <span className="sq-sidebar__marker" aria-hidden="true" />
                      <Glyph size={17} className="sq-sidebar__icon" />
                      {showLabels ? (
                        <span className="sq-sidebar__text">{item.label}</span>
                      ) : (
                        <span className="sq-sr-only">{item.label}</span>
                      )}
                    </NavLink>
                  )

                  return (
                    <li key={item.to}>
                      {showLabels ? link : <Tooltip text={item.label}>{link}</Tooltip>}
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </nav>

        {!compact ? (
          <div className="sq-sidebar__foot">
            <IconButton
              label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              onClick={onToggleCollapsed}
              aria-expanded={!collapsed}
              aria-controls="sq-sidebar"
            >
              <CollapseIcon size={16} />
            </IconButton>
          </div>
        ) : null}
      </aside>
    </>
  )
}
