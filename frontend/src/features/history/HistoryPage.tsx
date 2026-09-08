import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Skeleton, StateBlock, Tag } from '../../components/ui'
import { HistoryIcon } from '../../components/icons'
import { listTasks } from '../../services/satquery'
import { errorMessage } from '../../services/http'
import { useWorkspace } from '../../context/workspaceContext'
import { STATUS_META } from '../../utils/labels'
import { formatRelative } from '../../utils/format'
import type { TaskListEntry } from '../../types/api'
import './history.css'

/**
 * Analyses the service has run.
 *
 * The list comes from `GET /api/tasks`, which is the authority on what still
 * exists - the backend keeps a bounded, in-memory store, so a task can be
 * genuinely gone. The browser's own record supplies the submission time and
 * round trip, which the API does not carry.
 */
export function HistoryPage() {
  const { records, forgetRecords } = useWorkspace()
  const [tasks, setTasks] = useState<TaskListEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listTasks(50, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setTasks(response)
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(errorMessage(cause))
      })
    return () => controller.abort()
  }, [])

  const localFor = (taskId: string) => records.find((entry) => entry.taskId === taskId)

  return (
    <div className="sq-page">
      <header className="sq-page__head">
        <div>
          <h1 className="sq-page__title">History</h1>
          <p className="sq-page__lede">
            Analyses this service has run. Results are held in memory, so they do
            not survive a restart of the backend.
          </p>
        </div>
        {records.length > 0 ? (
          <Button size="sm" variant="ghost" onClick={forgetRecords}>
            Clear local timings
          </Button>
        ) : null}
      </header>

      {error ? (
        <StateBlock
          icon={<HistoryIcon size={20} />}
          tone="warning"
          title="History could not be loaded"
          body={error}
        />
      ) : tasks === null ? (
        <div className="sq-history">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} height={68} radius={10} />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <StateBlock
          icon={<HistoryIcon size={20} />}
          title="Nothing has been analysed yet"
          body="Once you ask SatQuery a question, every run appears here with its answer and its result."
          actions={
            <Link to="/" className="sq-btn sq-btn--primary">
              Ask the first question
            </Link>
          }
        />
      ) : (
        <ul className="sq-history">
          {tasks.map((task) => {
            const status = STATUS_META[task.status]
            const local = localFor(task.task_id)
            return (
              <li key={task.task_id}>
                <Link to={`/results/${task.task_id}`} className="sq-history__row">
                  <div className="sq-history__main">
                    <span className="sq-history__query">{task.query}</span>
                    <span className="sq-history__answer">{task.answer}</span>
                  </div>
                  <div className="sq-history__meta">
                    <Tag tone={status.tone}>{status.label}</Tag>
                    {local ? (
                      <span className="sq-history__time">
                        {formatRelative(local.submittedAt)}
                      </span>
                    ) : null}
                  </div>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
