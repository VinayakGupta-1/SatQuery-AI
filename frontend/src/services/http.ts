/**
 * The one place the application talks to the network.
 *
 * Every backend failure arrives in the same envelope (`app/api/errors.py`), so
 * this module turns that envelope into a single `ApiError` type carrying a
 * message that is already safe to show a user. Callers never see a raw
 * `Response`, never parse an error body, and never have to guess whether a
 * failure was transport-level or application-level.
 */

import { apiUrl } from './config'
import type { ErrorEnvelope } from '../types/api'

export type ApiErrorKind =
  /** The request never reached the server. */
  | 'offline'
  /** The request was aborted by the caller. */
  | 'aborted'
  /** The server rejected the request (4xx). */
  | 'rejected'
  /** The server failed (5xx). */
  | 'server'

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number
  /** Stable machine code from the backend, e.g. `invalid_upload`. */
  readonly code: string
  /** Per-field context, when the failure was field-level. */
  readonly fields: { field: string; message: string }[]
  /** Present on unexpected server failures; worth quoting in a bug report. */
  readonly incidentId: string | null

  constructor(init: {
    message: string
    kind: ApiErrorKind
    status?: number
    code?: string
    fields?: { field: string; message: string }[]
    incidentId?: string | null
  }) {
    super(init.message)
    this.name = 'ApiError'
    this.kind = init.kind
    this.status = init.status ?? 0
    this.code = init.code ?? init.kind
    this.fields = init.fields ?? []
    this.incidentId = init.incidentId ?? null
  }

  /** True when retrying the identical request could plausibly succeed. */
  get retryable(): boolean {
    return this.kind === 'offline' || this.kind === 'server'
  }
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as ErrorEnvelope).message === 'string'
  )
}

async function toApiError(response: Response): Promise<ApiError> {
  const kind: ApiErrorKind = response.status >= 500 ? 'server' : 'rejected'
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // A non-JSON error body (a proxy error page, for instance).
  }

  if (isErrorEnvelope(body)) {
    return new ApiError({
      message: body.message,
      kind,
      status: response.status,
      code: body.code,
      fields: body.fields ?? [],
      incidentId: body.incident_id,
    })
  }

  return new ApiError({
    message:
      kind === 'server'
        ? 'The analysis service reported an unexpected error.'
        : `The request was refused (HTTP ${response.status}).`,
    kind,
    status: response.status,
  })
}

export interface RequestOptions {
  signal?: AbortSignal
  /** Report upload progress, 0..1. Only honoured by `postForm`. */
  onUploadProgress?: (fraction: number) => void
}

async function send<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(apiUrl(path), init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError({ message: 'The request was cancelled.', kind: 'aborted' })
    }
    throw new ApiError({
      message:
        'The analysis service could not be reached. Check that the SatQuery backend is running.',
      kind: 'offline',
    })
  }

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function get<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return send<T>(path, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal: options.signal,
  })
}

/**
 * POST a multipart body, with real upload progress.
 *
 * `fetch` cannot report request progress, and a satellite scene is large
 * enough that a silent upload looks like a hung application. XHR is used here
 * for that single reason; everything else in the service layer uses `fetch`.
 */
export function postForm<T>(
  path: string,
  form: FormData,
  options: RequestOptions = {},
): Promise<T> {
  if (!options.onUploadProgress) {
    return send<T>(path, { method: 'POST', body: form, signal: options.signal })
  }

  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', apiUrl(path))
    request.responseType = 'text'
    request.setRequestHeader('Accept', 'application/json')

    const abort = () => request.abort()
    options.signal?.addEventListener('abort', abort, { once: true })

    const finish = () => options.signal?.removeEventListener('abort', abort)

    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        options.onUploadProgress?.(event.loaded / event.total)
      }
    }

    request.onload = () => {
      finish()
      let body: unknown = null
      try {
        body = JSON.parse(request.responseText)
      } catch {
        body = null
      }

      if (request.status >= 200 && request.status < 300) {
        resolve(body as T)
        return
      }

      const kind: ApiErrorKind = request.status >= 500 ? 'server' : 'rejected'
      if (isErrorEnvelope(body)) {
        reject(
          new ApiError({
            message: body.message,
            kind,
            status: request.status,
            code: body.code,
            fields: body.fields ?? [],
            incidentId: body.incident_id,
          }),
        )
        return
      }
      reject(
        new ApiError({
          message:
            kind === 'server'
              ? 'The analysis service reported an unexpected error.'
              : `The request was refused (HTTP ${request.status}).`,
          kind,
          status: request.status,
        }),
      )
    }

    request.onerror = () => {
      finish()
      reject(
        new ApiError({
          message:
            'The analysis service could not be reached. Check that the SatQuery backend is running.',
          kind: 'offline',
        }),
      )
    }

    request.onabort = () => {
      finish()
      reject(new ApiError({ message: 'The analysis was cancelled.', kind: 'aborted' }))
    }

    request.send(form)
  })
}

/** Narrow an unknown caught value to a user-presentable message. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
