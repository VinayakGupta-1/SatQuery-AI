import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { useIsCompact } from '../../hooks/useMediaQuery'
import { useLocalStorage } from '../../hooks/useLocalStorage'
import './workspace.css'

/**
 * The workspace shell: top bar, navigation, and one scrolling main region.
 *
 * The shell never scrolls; `main` does. That keeps the top bar and the
 * navigation fixed without any position juggling, and means a long result page
 * cannot push the chrome off screen.
 */
export function WorkspaceLayout() {
  const compact = useIsCompact()
  const location = useLocation()
  const [collapsed, setCollapsed] = useLocalStorage('satquery.sidebar.collapsed', false)
  const [drawerOpen, setDrawerOpen] = useState(false)

  // A route change closes the drawer and returns the reading position to the
  // top of the new screen.
  useEffect(() => {
    setDrawerOpen(false)
    document.getElementById('sq-main')?.scrollTo({ top: 0 })
  }, [location.pathname])

  return (
    <div
      className={`sq-shell${collapsed && !compact ? ' sq-shell--collapsed' : ''}`}
    >
      <a className="sq-skip" href="#sq-main">
        Skip to workspace
      </a>

      <div className="sq-shell__stars" aria-hidden="true" />

      <TopBar compact={compact} onOpenNavigation={() => setDrawerOpen(true)} />

      <Sidebar
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((value) => !value)}
        compact={compact}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />

      <main className="sq-main" id="sq-main" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
