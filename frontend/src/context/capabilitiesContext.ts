import { createContext, useContext } from 'react'
import type { CapabilitiesResponse, ToolSummary } from '../types/api'

export interface CapabilitiesState {
  capabilities: CapabilitiesResponse | null
  loading: boolean
  /** A user-presentable message when the service could not be described. */
  error: string | null
  reload: () => void
  /** Look up a registry entry by id. */
  toolById: (toolId: string | null | undefined) => ToolSummary | null
  /** Only the tools that can actually execute in this deployment. */
  executableTools: ToolSummary[]
  /** True once the service has answered at least once. */
  online: boolean
}

export const CapabilitiesContext = createContext<CapabilitiesState | null>(null)

export function useCapabilities(): CapabilitiesState {
  const value = useContext(CapabilitiesContext)
  if (!value) {
    throw new Error('useCapabilities must be used inside <CapabilitiesProvider>.')
  }
  return value
}
