import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ResultView } from './ResultView'
import { Skeleton, StateBlock } from '../../components/ui'
import { AlertIcon } from '../../components/icons'
import { getTask } from '../../services/satquery'
import { errorMessage } from '../../services/http'
import { useWorkspace } from '../../context/workspaceContext'
import type { TaskResponse } from '../../types/api'

/**
 * One result, addressable by URL.
 *
 * A result the user has just produced is already in memory, so it renders
 * instantly. One reached from history is fetched from `GET /api/tasks/{id}`.
 *
 * The backend's task store is in-memory and bounded, so a task can genuinely
 * be gone after a restart. That is reported as what it is - the record has
 * expired - rather than as a failure.
 */
export function ResultPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const { run, records } = useWorkspace()

  const inMemory =
    run.result && run.result.task_id === taskId ? run.result : null

  const [result, setResult] = useState<TaskResponse | null>(inMemory)
  const [loading, setLoading] = useState(!inMemory)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!taskId) return
    if (inMemory) {
      setResult(inMemory)
      setLoading(false)
      setError(null)
      return
    }

    const controller = new AbortController()
    setLoading(true)
    setError(null)

    getTask(taskId, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setResult(response)
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(errorMessage(cause))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [taskId, inMemory])

  const record = records.find((entry) => entry.taskId === taskId)

  if (loading) {
    return (
      <div className="sq-page">
        <div className="sq-result__skeleton">
          <Skeleton height={18} width="42%" />
          <Skeleton height={36} width="76%" />
          <Skeleton height={280} radius={12} />
          <Skeleton height={96} radius={10} />
        </div>
      </div>
    )
  }

  if (error || !result) {
    return (
      <div className="sq-page">
        <StateBlock
          icon={<AlertIcon size={20} />}
          tone="warning"
          title="This result is no longer available"
          body={
            <>
              <p>
                {error ??
                  'The analysis service has no record of this task. Results are kept in memory and are lost when the service restarts.'}
              </p>
              {record ? (
                <p className="sq-muted">You asked: “{record.query}”</p>
              ) : null}
            </>
          }
          actions={
            <>
              <Link to="/" className="sq-btn sq-btn--primary">
                Start a new query
              </Link>
              <Link to="/history" className="sq-btn sq-btn--ghost">
                Back to history
              </Link>
            </>
          }
        />
      </div>
    )
  }

  return (
    <div className="sq-page sq-page--wide">
      {/* The round trip is only meaningful for a run this browser made, so it
          comes from the local record and never from an unrelated run. */}
      <ResultView
        result={result}
        durationMs={record?.durationMs ?? (inMemory ? run.durationMs : null)}
      />
    </div>
  )
}
