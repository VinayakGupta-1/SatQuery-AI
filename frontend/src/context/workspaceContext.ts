import { createContext, useContext } from 'react'
import type { ApiError } from '../services/http'
import type { TaskResponse, ValidationResponse } from '../types/api'

/** One raster staged for the next analysis. */
export interface StagedFile {
  id: string
  file: File
  name: string
  size: number
  /** Set when the file was rejected before it was ever sent. */
  problem: string | null
}

export type RunPhase = 'idle' | 'uploading' | 'analysing' | 'complete' | 'failed'

export interface RunState {
  phase: RunPhase
  query: string
  /** 0..1 while the imagery is being sent. */
  uploaded: number
  startedAt: number | null
  /** Wall-clock round trip, measured in the browser. */
  durationMs: number | null
  result: TaskResponse | null
  error: ApiError | null
}

/** What the browser knows about a run that the backend's list does not. */
export interface RunRecord {
  taskId: string
  query: string
  submittedAt: string
  durationMs: number | null
  status: TaskResponse['status']
  tool: string | null
}

export interface SavedQuery {
  id: string
  text: string
  savedAt: string
}

export interface WorkspaceState {
  /* ---- staged imagery ------------------------------------------------- */
  files: StagedFile[]
  addFiles: (files: FileList | File[]) => void
  removeFile: (id: string) => void
  clearFiles: () => void

  /** Treat the staged files as bands of one scene rather than separate images. */
  asScene: boolean
  setAsScene: (value: boolean) => void
  /** Optional sensor hint, e.g. `sentinel2`. */
  sensor: string
  setSensor: (value: string) => void

  /* ---- the current run ------------------------------------------------ */
  run: RunState
  submit: (query: string) => Promise<TaskResponse | null>
  cancel: () => void
  reset: () => void

  /** Dry run against `/api/tasks/validate`. Never executes a tool. */
  check: () => Promise<void>
  checking: boolean
  checkResult: ValidationResponse | null
  clearCheck: () => void

  /* ---- history and saved queries -------------------------------------- */
  /** Client-side record of runs made from this browser, newest first. */
  records: RunRecord[]
  forgetRecords: () => void

  saved: SavedQuery[]
  saveQuery: (text: string) => void
  removeSaved: (id: string) => void

  /** Prefill the composer, used by history and saved-query links. */
  draft: string
  setDraft: (value: string) => void
}

export const WorkspaceContext = createContext<WorkspaceState | null>(null)

export function useWorkspace(): WorkspaceState {
  const value = useContext(WorkspaceContext)
  if (!value) throw new Error('useWorkspace must be used inside <WorkspaceProvider>.')
  return value
}
