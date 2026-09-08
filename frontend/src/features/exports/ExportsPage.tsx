import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Disclosure, Skeleton, StateBlock, Tag } from '../../components/ui'
import { ExportIcon } from '../../components/icons'
import { ArtifactList } from '../results/parts/ArtifactList'
import { getTask, listTasks } from '../../services/satquery'
import { errorMessage } from '../../services/http'
import type { TaskListEntry, TaskResponse } from '../../types/api'

/**
 * Every raster the service has produced, as downloads.
 *
 * `GET /api/tasks` lists runs but not their artifacts, so the file list for
 * a run is fetched only when its row is opened. Fetching all of them up front
 * would be a request per task for files most people will never download.
 */
export function ExportsPage() {
  const [tasks, setTasks] = useState<TaskListEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listTasks(50, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) {
          setTasks(response.filter((task) => task.status === 'success'))
        }
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(errorMessage(cause))
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="sq-page">
      <header className="sq-page__head">
        <div>
          <h1 className="sq-page__title">Exports</h1>
          <p className="sq-page__lede">
            GeoTIFFs produced by completed analyses. Each carries the source
            grid and CRS, so it opens directly in QGIS or ArcGIS.
          </p>
        </div>
      </header>

      {error ? (
        <StateBlock
          icon={<ExportIcon size={20} />}
          tone="warning"
          title="Exports could not be listed"
          body={error}
        />
      ) : tasks === null ? (
        <>
          <Skeleton height={56} radius={10} />
          <Skeleton height={56} radius={10} />
        </>
      ) : tasks.length === 0 ? (
        <StateBlock
          icon={<ExportIcon size={20} />}
          title="No exports yet"
          body="Analyses that produce a raster — an index, a change map — leave their output here to download."
          actions={
            <Link to="/" className="sq-btn sq-btn--primary">
              Run an analysis
            </Link>
          }
        />
      ) : (
        <div className="sq-result__advanced">
          {tasks.map((task) => (
            <TaskExports key={task.task_id} task={task} />
          ))}
        </div>
      )}
    </div>
  )
}

function TaskExports({ task }: { task: TaskListEntry }) {
  const [detail, setDetail] = useState<TaskResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [opened, setOpened] = useState(false)

  useEffect(() => {
    if (!opened || detail || loading) return
    const controller = new AbortController()
    setLoading(true)
    getTask(task.task_id, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setDetail(response)
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setFailed(errorMessage(cause))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [opened, detail, loading, task.task_id])

  return (
    <Disclosure
      icon={<ExportIcon size={15} />}
      onOpenChange={(open) => {
        if (open) setOpened(true)
      }}
      summary={
        <span className="sq-exports__summary">
          <span className="sq-exports__query">{task.query}</span>
          {detail ? (
            <Tag tone="neutral">
              {detail.artifacts.length} file
              {detail.artifacts.length === 1 ? '' : 's'}
            </Tag>
          ) : null}
        </span>
      }
    >
      {loading ? (
        <Skeleton height={54} radius={8} />
      ) : failed ? (
        <p className="sq-muted">{failed}</p>
      ) : detail && detail.artifacts.length > 0 ? (
        <>
          <ArtifactList artifacts={detail.artifacts} />
          <p className="sq-cap__param-note">
            <Link to={`/results/${task.task_id}`}>Open the full result</Link>
          </p>
        </>
      ) : (
        <p className="sq-muted">This analysis produced no downloadable raster.</p>
      )}
    </Disclosure>
  )
}
