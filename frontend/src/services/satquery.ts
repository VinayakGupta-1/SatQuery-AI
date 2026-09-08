/**
 * The SatQuery backend, as functions.
 *
 * One function per endpoint the backend actually publishes. No endpoint is
 * invented here: if it is in this file, it exists in `backend/app/api`.
 *
 *   GET  /api/health                                  health()
 *   GET  /api/capabilities                            capabilities()
 *   GET  /api/tools                                   tools()
 *   GET  /api/tools/{tool_id}                         tool()
 *   POST /api/tasks            (alias /analyze)       analyze()
 *   POST /api/tasks/validate   (alias /analyze/validate)  validateRequest()
 *   GET  /api/tasks                                   listTasks()
 *   GET  /api/tasks/{task_id}  (alias /results/{id})  getTask()
 *   GET  /api/tasks/{task_id}/artifacts/{artifact_id} artifactUrl()
 */

import { get, postForm, type RequestOptions } from './http'
import { apiUrl } from './config'
import type {
  CapabilitiesResponse,
  HealthResponse,
  TaskListEntry,
  TaskResponse,
  ToolSummary,
  ValidationResponse,
} from '../types/api'

export function health(options?: RequestOptions): Promise<HealthResponse> {
  return get<HealthResponse>('/api/health', options)
}

export function capabilities(options?: RequestOptions): Promise<CapabilitiesResponse> {
  return get<CapabilitiesResponse>('/api/capabilities', options)
}

export function tools(
  implementedOnly = false,
  options?: RequestOptions,
): Promise<ToolSummary[]> {
  const query = implementedOnly ? '?implemented_only=true' : ''
  return get<ToolSummary[]>(`/api/tools${query}`, options)
}

export function tool(toolId: string, options?: RequestOptions): Promise<ToolSummary> {
  return get<ToolSummary>(`/api/tools/${encodeURIComponent(toolId)}`, options)
}

/** The request body of `POST /api/tasks`, as the backend's form fields. */
export interface AnalysisRequest {
  query: string
  files: File[]
  /** Treat the uploads as bands of one scene rather than separate images. */
  asScene?: boolean
  /** Sensor name, e.g. `sentinel2`. Disambiguates numeric band names. */
  sensor?: string | null
  /** Explicit tool parameters. Serialised to the `parameters` JSON field. */
  parameters?: Record<string, unknown> | null
}

function buildForm(request: AnalysisRequest, includeParameters: boolean): FormData {
  const form = new FormData()
  form.append('query', request.query)
  for (const file of request.files) form.append('files', file, file.name)
  form.append('as_scene', request.asScene ? 'true' : 'false')
  if (request.sensor?.trim()) form.append('sensor', request.sensor.trim())
  if (includeParameters && request.parameters && Object.keys(request.parameters).length > 0) {
    form.append('parameters', JSON.stringify(request.parameters))
  }
  return form
}

/** Run the full pipeline. Returns 200 with an explanation even when refused. */
export function analyze(
  request: AnalysisRequest,
  options?: RequestOptions,
): Promise<TaskResponse> {
  return postForm<TaskResponse>('/api/tasks', buildForm(request, true), options)
}

/**
 * Dry-run: check whether the request would execute, without executing it.
 *
 * The backend's `/validate` route does not accept the `parameters` field, so
 * it is deliberately omitted from the body.
 */
export function validateRequest(
  request: AnalysisRequest,
  options?: RequestOptions,
): Promise<ValidationResponse> {
  return postForm<ValidationResponse>(
    '/api/tasks/validate',
    buildForm(request, false),
    options,
  )
}

export function listTasks(limit = 50, options?: RequestOptions): Promise<TaskListEntry[]> {
  return get<TaskListEntry[]>(`/api/tasks?limit=${limit}`, options)
}

export function getTask(taskId: string, options?: RequestOptions): Promise<TaskResponse> {
  return get<TaskResponse>(`/api/tasks/${encodeURIComponent(taskId)}`, options)
}

/** Absolute URL for an artifact link returned on a task response. */
export function artifactUrl(link: { url: string }): string {
  return apiUrl(link.url)
}
