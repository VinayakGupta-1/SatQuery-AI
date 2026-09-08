import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { capabilities as fetchCapabilities } from '../services/satquery'
import { errorMessage } from '../services/http'
import type { CapabilitiesResponse, ToolSummary } from '../types/api'
import { CapabilitiesContext, type CapabilitiesState } from './capabilitiesContext'

/**
 * `/api/capabilities` for the whole application.
 *
 * The backend generates that response from the tool registry on every call, so
 * it is the authoritative statement of what this deployment can do. Loading it
 * once here means the upload limits, accepted formats, executable tool list
 * and query suggestions all come from the server rather than from constants
 * duplicated in the frontend.
 */
export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    fetchCapabilities({ signal: controller.signal })
      .then((response) => {
        setCapabilities(response)
        setError(null)
      })
      .catch((cause) => {
        if (controller.signal.aborted) return
        setError(errorMessage(cause))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [nonce])

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  const value = useMemo<CapabilitiesState>(() => {
    const tools = capabilities?.tools ?? []
    const index = new Map<string, ToolSummary>(tools.map((tool) => [tool.tool_id, tool]))
    return {
      capabilities,
      loading,
      error,
      reload,
      online: capabilities !== null,
      toolById: (toolId) => (toolId ? (index.get(toolId) ?? null) : null),
      executableTools: tools.filter((tool) => tool.implemented && tool.enabled),
    }
  }, [capabilities, loading, error, reload])

  return (
    <CapabilitiesContext.Provider value={value}>{children}</CapabilitiesContext.Provider>
  )
}
