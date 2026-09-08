import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { analyze, validateRequest } from '../services/satquery'
import { ApiError } from '../services/http'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { useCapabilities } from './capabilitiesContext'
import {
  WorkspaceContext,
  type RunRecord,
  type RunState,
  type SavedQuery,
  type StagedFile,
  type WorkspaceState,
} from './workspaceContext'
import type { TaskResponse, ValidationResponse } from '../types/api'

const IDLE_RUN: RunState = {
  phase: 'idle',
  query: '',
  uploaded: 0,
  startedAt: null,
  durationMs: null,
  result: null,
  error: null,
}

let fileCounter = 0

/** Ordinary picture formats people reach for first. */
const PHOTO_EXTENSIONS = new Set([
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
  '.gif',
  '.bmp',
  '.heic',
  '.avif',
])

/**
 * Why a file was refused, in terms the person can act on.
 *
 * "Unsupported extension" is true but unhelpful. A photograph is refused for a
 * substantive reason - it carries no spectral bands and no georeferencing, so
 * there is nothing to compute an index from - and saying so is the difference
 * between a dead end and a next step.
 */
function rejectionReason(extension: string, accepted: string[]): string {
  if (PHOTO_EXTENSIONS.has(extension)) {
    return (
      `${extension.slice(1).toUpperCase()} is a picture format, not satellite data. ` +
      'It carries no spectral bands and no georeferencing, so an index cannot be ' +
      'computed from it. SatQuery needs a GeoTIFF scene.'
    )
  }
  return `SatQuery reads ${accepted.join(', ')} rasters. This file is ${
    extension || 'of an unknown type'
  }.`
}

/**
 * Everything the workspace holds between screens.
 *
 * Staged files live only in memory: a `File` cannot be persisted, and a raster
 * the user picked in a previous session is not something this application
 * should pretend to still have. Run history and saved queries do persist,
 * because they are text.
 *
 * The run itself is held here rather than in the query screen so that
 * navigating to History mid-analysis does not abandon the request.
 */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { capabilities } = useCapabilities()

  const [files, setFiles] = useState<StagedFile[]>([])
  const [asScene, setAsScene] = useState(false)
  const [sensor, setSensor] = useState('')
  const [run, setRun] = useState<RunState>(IDLE_RUN)
  const [checking, setChecking] = useState(false)
  const [checkResult, setCheckResult] = useState<ValidationResponse | null>(null)
  const [draft, setDraft] = useState('')

  const [records, setRecords] = useLocalStorage<RunRecord[]>('satquery.records', [])
  const [saved, setSaved] = useLocalStorage<SavedQuery[]>('satquery.saved', [])

  const controllerRef = useRef<AbortController | null>(null)

  /* ---- staged imagery -------------------------------------------------- */

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const accepted = capabilities?.accepted_formats ?? []
      const maxBytes = capabilities?.max_upload_bytes ?? Number.POSITIVE_INFINITY

      const staged: StagedFile[] = Array.from(incoming).map((file) => {
        const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
        let problem: string | null = null

        // Checked here only to give immediate feedback. The backend performs
        // the authoritative check when the file is actually sent, and its
        // verdict always wins.
        if (accepted.length > 0 && !accepted.includes(extension)) {
          problem = rejectionReason(extension, accepted)
        } else if (file.size === 0) {
          problem = 'This file is empty.'
        } else if (file.size > maxBytes) {
          problem = 'This file is larger than the service accepts.'
        }

        fileCounter += 1
        return {
          id: `staged_${fileCounter}`,
          file,
          name: file.name,
          size: file.size,
          problem,
        }
      })

      setFiles((current) => [...current, ...staged])
      setCheckResult(null)
    },
    [capabilities],
  )

  const removeFile = useCallback((id: string) => {
    setFiles((current) => current.filter((entry) => entry.id !== id))
    setCheckResult(null)
  }, [])

  const clearFiles = useCallback(() => {
    setFiles([])
    setCheckResult(null)
  }, [])

  /* ---- running --------------------------------------------------------- */

  const reset = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setRun(IDLE_RUN)
  }, [])

  const cancel = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  const submit = useCallback(
    async (query: string): Promise<TaskResponse | null> => {
      const usable = files.filter((entry) => !entry.problem).map((entry) => entry.file)
      const controller = new AbortController()
      controllerRef.current = controller
      const startedAt = Date.now()

      setRun({
        ...IDLE_RUN,
        phase: 'uploading',
        query,
        startedAt,
      })

      try {
        const result = await analyze(
          { query, files: usable, asScene, sensor: sensor || null },
          {
            signal: controller.signal,
            onUploadProgress: (fraction) => {
              setRun((current) =>
                current.phase === 'uploading'
                  ? {
                      ...current,
                      uploaded: fraction,
                      // The upload finishing is the moment the analysis starts,
                      // and it is the one stage boundary the client can observe.
                      phase: fraction >= 1 ? 'analysing' : 'uploading',
                    }
                  : current,
              )
            },
          },
        )

        const durationMs = Date.now() - startedAt
        setRun({
          phase: 'complete',
          query,
          uploaded: 1,
          startedAt,
          durationMs,
          result,
          error: null,
        })

        setRecords((current) =>
          [
            {
              taskId: result.task_id,
              query: result.query,
              submittedAt: new Date(startedAt).toISOString(),
              durationMs,
              status: result.status,
              tool: result.tool,
            },
            ...current.filter((entry) => entry.taskId !== result.task_id),
          ].slice(0, 60),
        )

        return result
      } catch (cause) {
        const error =
          cause instanceof ApiError
            ? cause
            : new ApiError({ message: 'The analysis could not be completed.', kind: 'server' })

        if (error.kind === 'aborted') {
          setRun(IDLE_RUN)
          return null
        }

        setRun({
          phase: 'failed',
          query,
          uploaded: 1,
          startedAt,
          durationMs: Date.now() - startedAt,
          result: null,
          error,
        })
        return null
      } finally {
        controllerRef.current = null
      }
    },
    [files, asScene, sensor, setRecords],
  )

  /* ---- dry run --------------------------------------------------------- */

  const check = useCallback(async () => {
    const usable = files.filter((entry) => !entry.problem).map((entry) => entry.file)
    if (usable.length === 0) return
    setChecking(true)
    try {
      const response = await validateRequest({
        query: draft.trim() || 'Describe this imagery.',
        files: usable,
        asScene,
        sensor: sensor || null,
      })
      setCheckResult(response)
    } catch (cause) {
      setCheckResult(null)
      // A failed dry run is surfaced through the run error channel so there is
      // one place errors appear rather than two.
      setRun((current) => ({
        ...current,
        phase: 'failed',
        error:
          cause instanceof ApiError
            ? cause
            : new ApiError({ message: 'The check could not be completed.', kind: 'server' }),
      }))
    } finally {
      setChecking(false)
    }
  }, [files, draft, asScene, sensor])

  const clearCheck = useCallback(() => setCheckResult(null), [])

  /* ---- saved queries --------------------------------------------------- */

  const saveQuery = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      setSaved((current) => {
        if (current.some((entry) => entry.text === trimmed)) return current
        return [
          { id: `saved_${Date.now()}`, text: trimmed, savedAt: new Date().toISOString() },
          ...current,
        ].slice(0, 40)
      })
    },
    [setSaved],
  )

  const removeSaved = useCallback(
    (id: string) => setSaved((current) => current.filter((entry) => entry.id !== id)),
    [setSaved],
  )

  const forgetRecords = useCallback(() => setRecords([]), [setRecords])

  const value = useMemo<WorkspaceState>(
    () => ({
      files,
      addFiles,
      removeFile,
      clearFiles,
      asScene,
      setAsScene,
      sensor,
      setSensor,
      run,
      submit,
      cancel,
      reset,
      check,
      checking,
      checkResult,
      clearCheck,
      records,
      forgetRecords,
      saved,
      saveQuery,
      removeSaved,
      draft,
      setDraft,
    }),
    [
      files,
      addFiles,
      removeFile,
      clearFiles,
      asScene,
      sensor,
      run,
      submit,
      cancel,
      reset,
      check,
      checking,
      checkResult,
      clearCheck,
      records,
      forgetRecords,
      saved,
      saveQuery,
      removeSaved,
      draft,
    ],
  )

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}
