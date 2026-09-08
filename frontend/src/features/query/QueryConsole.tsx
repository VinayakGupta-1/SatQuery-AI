import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { QueryComposer } from './QueryComposer'
import { AnalysisProgress } from './AnalysisProgress'
import { Button, Notice, StateBlock } from '../../components/ui'
import { AlertIcon, RefreshIcon } from '../../components/icons'
import { useWorkspace } from '../../context/workspaceContext'
import { useAuth } from '../../context/authContext'
import { useCapabilities } from '../../context/capabilitiesContext'
import './query.css'

/**
 * The workspace's index screen.
 *
 * Three states and nothing else: ask, analysing, or a failure that needs a
 * decision. A completed run is not a state here - it becomes a result, and the
 * screen hands over to `/results/:taskId` so the answer has an address.
 */
export function QueryConsole() {
  const navigate = useNavigate()
  const { session } = useAuth()
  const { error: serviceError, reload } = useCapabilities()
  const { run, submit, cancel, reset, setDraft } = useWorkspace()

  // A finished run leaves this screen for its own page.
  useEffect(() => {
    if (run.phase === 'complete' && run.result) {
      navigate(`/results/${run.result.task_id}`, { replace: true })
    }
  }, [run.phase, run.result, navigate])

  if (run.phase === 'uploading' || run.phase === 'analysing') {
    return (
      <div className="sq-page">
        <AnalysisProgress run={run} onCancel={cancel} />
      </div>
    )
  }

  if (run.phase === 'failed' && run.error) {
    const { error } = run
    return (
      <div className="sq-page">
        <StateBlock
          icon={<AlertIcon size={20} />}
          tone="danger"
          title={
            error.kind === 'offline'
              ? 'The analysis service could not be reached'
              : 'We could not complete this analysis'
          }
          body={
            <>
              <p>{error.message}</p>
              {error.fields.length > 0 ? (
                <ul className="sq-error-fields">
                  {error.fields.map((field) => (
                    <li key={field.field}>{field.message}</li>
                  ))}
                </ul>
              ) : null}
              {error.incidentId ? (
                <p className="sq-error-incident sq-mono">
                  Incident {error.incidentId}
                </p>
              ) : null}
            </>
          }
          actions={
            <>
              <Button
                variant="primary"
                onClick={() => {
                  setDraft(run.query)
                  reset()
                }}
              >
                {error.retryable ? 'Try again' : 'Edit the request'}
              </Button>
              <Button variant="ghost" onClick={reset}>
                Start over
              </Button>
            </>
          }
        />
      </div>
    )
  }

  return (
    <div className="sq-page sq-page--console">
      {serviceError ? (
        <Notice
          tone="danger"
          title="The analysis service is not responding"
          actions={
            <Button size="sm" icon={<RefreshIcon size={14} />} onClick={reload}>
              Retry
            </Button>
          }
        >
          Queries cannot run until the SatQuery backend is reachable. {serviceError}
        </Notice>
      ) : null}

      <QueryComposer
        operator={session?.operator.split(' ')[0] ?? 'operator'}
        onSubmit={(query) => void submit(query)}
      />
    </div>
  )
}
