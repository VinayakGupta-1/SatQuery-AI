import { useNavigate } from 'react-router-dom'
import {
  Button,
  Definition,
  Definitions,
  Notice,
  Panel,
  Skeleton,
  Tag,
} from '../../components/ui'
import { useAuth } from '../../context/authContext'
import { useCapabilities } from '../../context/capabilitiesContext'
import { useWorkspace } from '../../context/workspaceContext'
import { usePrefersReducedMotion } from '../../hooks/useMediaQuery'
import { API_BASE } from '../../services/config'
import { formatBytes, formatDate } from '../../utils/format'

/**
 * What this deployment is, and what this browser is holding.
 *
 * Everything on the left comes from the service's own `/api/capabilities`
 * response - the raster backend in use, whether GDAL is present, which
 * understanding provider is active. None of it is configurable from here,
 * because none of it is configurable over the API: it is set by environment
 * on the server. Showing it read-only is more useful than offering controls
 * that would not work.
 */
export function SettingsPage() {
  const navigate = useNavigate()
  const { session, signOut } = useAuth()
  const { capabilities, loading, error, reload } = useCapabilities()
  const { saved, records, forgetRecords } = useWorkspace()
  const reducedMotion = usePrefersReducedMotion()

  return (
    <div className="sq-page">
      <header className="sq-page__head">
        <div>
          <h1 className="sq-page__title">Settings</h1>
          <p className="sq-page__lede">
            The state of the analysis service, your session, and what is stored
            in this browser.
          </p>
        </div>
      </header>

      <Panel title="Analysis service">
        {loading ? (
          <Skeleton height={140} radius={8} />
        ) : error || !capabilities ? (
          <Notice
            tone="danger"
            title="Not reachable"
            actions={
              <Button size="sm" onClick={reload}>
                Retry
              </Button>
            }
          >
            {error ?? 'The service did not answer.'}
          </Notice>
        ) : (
          <Definitions>
            <Definition term="Endpoint">
              <span className="sq-mono">{API_BASE || window.location.origin}</span>
            </Definition>
            <Definition term="Version">
              <span className="sq-mono">{capabilities.version}</span>
            </Definition>
            <Definition term="Capabilities">
              {capabilities.executable.length} of {capabilities.tools.length}{' '}
              registered can execute
            </Definition>
            <Definition term="Raster backend">
              <span className="sq-mono">{capabilities.backend.raster_backend}</span>
              {capabilities.backend.supports_compressed_geotiff ? (
                <Tag tone="success">Compressed GeoTIFF</Tag>
              ) : (
                <Tag tone="warning">Uncompressed only</Tag>
              )}
            </Definition>
            <Definition term="Vectorised maths">
              {capabilities.backend.numpy_available ? 'numpy available' : 'pure Python'}
            </Definition>
            <Definition term="Query understanding">
              <span className="sq-mono">{capabilities.agent_provider}</span>
              {capabilities.agent_llm_enabled ? (
                <Tag tone="info">Hosted model</Tag>
              ) : (
                <Tag tone="neutral">Offline rules</Tag>
              )}
            </Definition>
            <Definition term="Upload limits">
              {formatBytes(capabilities.max_upload_bytes)} per file ·{' '}
              {capabilities.max_images_per_task} images per analysis
            </Definition>
            <Definition term="Accepted formats">
              <span className="sq-mono">{capabilities.accepted_formats.join(' ')}</span>
            </Definition>
          </Definitions>
        )}
      </Panel>

      <Panel title="Session">
        <Definitions>
          <Definition term="Operator">{session?.operator ?? '--'}</Definition>
          <Definition term="Identifier">
            <span className="sq-mono">{session?.identifier ?? '--'}</span>
          </Definition>
          <Definition term="Opened">{formatDate(session?.openedAt)}</Definition>
          <Definition term="Issued by">
            {session?.origin === 'server' ? 'The analysis service' : 'This device'}
          </Definition>
        </Definitions>

        <div style={{ marginTop: 'var(--sq-5)' }}>
          <Notice tone="info" title="How sessions work here">
            This deployment of the SatQuery backend publishes no authentication
            endpoint, so the workspace opens a session locally after confirming
            the service is reachable. Your passphrase is never transmitted and
            never stored. When the backend gains authentication, the session
            provider in <span className="sq-mono">services/auth.ts</span> is the
            only file that changes.
          </Notice>
        </div>

        <div style={{ marginTop: 'var(--sq-4)' }}>
          <Button
            variant="danger"
            onClick={() => {
              signOut()
              navigate('/login', { replace: true })
            }}
          >
            Sign out
          </Button>
        </div>
      </Panel>

      <Panel title="Stored in this browser">
        <Definitions>
          <Definition term="Saved queries">{saved.length}</Definition>
          <Definition term="Run records">{records.length}</Definition>
          <Definition term="Motion">
            {reducedMotion
              ? 'Reduced — the workspace follows your system setting'
              : 'Full — the workspace follows your system setting'}
          </Definition>
        </Definitions>

        <p className="sq-page__lede" style={{ marginTop: 'var(--sq-4)' }}>
          Run records hold the question, the time it was submitted and how long
          the round trip took. No imagery is kept in the browser between
          sessions.
        </p>

        {records.length > 0 ? (
          <div style={{ marginTop: 'var(--sq-4)' }}>
            <Button variant="secondary" onClick={forgetRecords}>
              Clear run records
            </Button>
          </div>
        ) : null}
      </Panel>
    </div>
  )
}
