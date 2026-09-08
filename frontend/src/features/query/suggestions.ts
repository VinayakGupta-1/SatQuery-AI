import type { CapabilitiesResponse } from '../../types/api'

/**
 * Example questions, derived from what the deployment can actually run.
 *
 * The suggestions are keyed by tool id and filtered against
 * `capabilities.executable`, so a user is never offered a question the service
 * would have to refuse. If the registry gains a tool and binds an
 * implementation, its example appears here without any other change.
 */
interface Suggestion {
  toolId: string
  text: string
  /** How many rasters the question implies, for the composer hint. */
  images: number
}

const SUGGESTIONS: Suggestion[] = [
  {
    toolId: 'ndvi',
    text: 'How healthy is the vegetation in this scene?',
    images: 1,
  },
  {
    toolId: 'ndwi',
    text: 'Map the surface water in this image.',
    images: 1,
  },
  {
    toolId: 'ndbi',
    text: 'Where are the built-up areas in this scene?',
    images: 1,
  },
  {
    toolId: 'change_detection',
    text: 'Compare these two dates and show me what changed.',
    images: 2,
  },
  {
    toolId: 'change_detection',
    text: 'Has vegetation been lost between these two images?',
    images: 2,
  },
  {
    toolId: 'ndvi',
    text: 'Show the share of this area under dense vegetation.',
    images: 1,
  },
]

export function suggestionsFor(
  capabilities: CapabilitiesResponse | null,
  limit = 4,
): Suggestion[] {
  if (!capabilities) return []
  const executable = new Set(capabilities.executable)
  const available = SUGGESTIONS.filter((entry) => executable.has(entry.toolId))

  // One example per capability first, so the row shows breadth before depth.
  const seen = new Set<string>()
  const primary = available.filter((entry) => {
    if (seen.has(entry.toolId)) return false
    seen.add(entry.toolId)
    return true
  })
  const rest = available.filter((entry) => !primary.includes(entry))
  return [...primary, ...rest].slice(0, limit)
}
