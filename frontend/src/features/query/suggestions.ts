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

// Ordered for breadth: the first example of each capability is what the
// composer shows first, so the row reads as a tour of what can be asked.
const SUGGESTIONS: Suggestion[] = [
  {
    toolId: 'ndvi',
    text: 'How healthy is the vegetation in this scene?',
    images: 1,
  },
  {
    toolId: 'land_cover_classification',
    text: 'Classify the land cover in this image.',
    images: 1,
  },
  {
    toolId: 'change_detection',
    text: 'Compare these two dates and show me what changed.',
    images: 2,
  },
  {
    toolId: 'object_detection',
    text: 'How many water bodies are in this scene?',
    images: 1,
  },
  {
    toolId: 'sar_analysis',
    text: 'Find the areas affected by flooding in this radar image.',
    images: 1,
  },
  {
    toolId: 'satellite_vqa',
    text: 'Is there a river or a reservoir in this image?',
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
    text: 'Has vegetation been lost between these two images?',
    images: 2,
  },
  {
    toolId: 'ndvi',
    text: 'Show the share of this area under dense vegetation.',
    images: 1,
  },
]

/**
 * The same questions about named places, for when nothing is attached and the
 * server fetches the imagery. Each names a place the geocoder resolves and,
 * where it matters, a period with imagery in the archive.
 */
const PLACE_SUGGESTIONS: Suggestion[] = [
  { toolId: 'ndvi', text: 'How healthy is the vegetation in Pune?', images: 1 },
  {
    toolId: 'land_cover_classification',
    text: 'Classify the land cover around Nagpur.',
    images: 1,
  },
  {
    toolId: 'change_detection',
    text: 'Has vegetation been lost around Hosur between 2019 and 2025?',
    images: 2,
  },
  {
    toolId: 'sar_analysis',
    text: 'Find the areas affected by flooding near Kochi in August 2024.',
    images: 1,
  },
  { toolId: 'object_detection', text: 'How many water bodies are around Bhopal?', images: 1 },
  { toolId: 'satellite_vqa', text: 'Is there a river near Varanasi?', images: 1 },
  { toolId: 'ndwi', text: 'Map the surface water around Chilika Lake.', images: 1 },
  { toolId: 'ndbi', text: 'Where are the built-up areas in Gurugram?', images: 1 },
]

export function suggestionsFor(
  capabilities: CapabilitiesResponse | null,
  limit = 4,
  places = false,
): Suggestion[] {
  if (!capabilities) return []
  const executable = new Set(capabilities.executable)
  const pool = places ? PLACE_SUGGESTIONS : SUGGESTIONS
  const available = pool.filter((entry) => executable.has(entry.toolId))

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
