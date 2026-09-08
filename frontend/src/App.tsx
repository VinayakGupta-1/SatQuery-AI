import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthProvider'
import { CapabilitiesProvider } from './context/CapabilitiesProvider'
import { WorkspaceProvider } from './context/WorkspaceProvider'
import { ErrorBoundary } from './app/ErrorBoundary'
import { RequireSession } from './app/RequireSession'
import { NotFoundPage } from './app/NotFoundPage'
import { LaunchVeil } from './features/launch/LaunchVeil'
import { WorkspaceLayout } from './features/workspace/WorkspaceLayout'
import { QueryConsole } from './features/query/QueryConsole'
import { ResultPage } from './features/results/ResultPage'
import { HistoryPage } from './features/history/HistoryPage'
import { SavedPage } from './features/history/SavedPage'
import { ImageryPage } from './features/imagery/ImageryPage'
import { CapabilitiesPage } from './features/capabilities/CapabilitiesPage'
import { ExportsPage } from './features/exports/ExportsPage'
import { SettingsPage } from './features/settings/SettingsPage'
import { HelpPage } from './features/help/HelpPage'
import './app/app.css'

/**
 * The sign-in screen is code-split.
 *
 * It is the only screen that pulls in three.js, and a returning operator with
 * a stored session never sees it. Splitting it keeps roughly half a megabyte
 * of renderer out of the workspace's initial load.
 */
const LoginPage = lazy(() => import('./features/auth/LoginPage'))

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <CapabilitiesProvider>
          <WorkspaceProvider>
            <ErrorBoundary>
              <Routes>
                <Route
                  path="/login"
                  element={
                    <Suspense fallback={<div className="sq-boot" aria-busy="true" />}>
                      <LoginPage />
                    </Suspense>
                  }
                />

                <Route
                  element={
                    <RequireSession>
                      <WorkspaceLayout />
                    </RequireSession>
                  }
                >
                  <Route index element={<QueryConsole />} />
                  <Route path="/results/:taskId" element={<ResultPage />} />
                  <Route path="/history" element={<HistoryPage />} />
                  <Route path="/saved" element={<SavedPage />} />
                  <Route path="/imagery" element={<ImageryPage />} />
                  <Route path="/capabilities" element={<CapabilitiesPage />} />
                  <Route path="/exports" element={<ExportsPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/help" element={<HelpPage />} />
                  <Route path="/results" element={<Navigate to="/history" replace />} />
                  <Route path="*" element={<NotFoundPage />} />
                </Route>
              </Routes>
            </ErrorBoundary>
          </WorkspaceProvider>
        </CapabilitiesProvider>
      </AuthProvider>

      {/* Outside the router on purpose: it has to survive the navigation it
          is covering. */}
      <LaunchVeil />
    </BrowserRouter>
  )
}
