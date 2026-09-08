import { Notice, Panel, Stat, StatGrid } from '../../../components/ui'
import { formatPercent } from '../../../utils/format'
import { humanise } from '../../../utils/labels'
import type { TaskResponse } from '../../../types/api'

/**
 * A detection result.
 *
 * ------------------------------------------------------------------------
 * WAITING ON THE BACKEND.
 *
 * `object_detection` is present in the registry but has no implementation
 * bound (`app/tools/binding.py`), so the pipeline blocks before execution and
 * this component is not reached in the current deployment. More importantly,
 * the backend does not yet define what a detection payload looks like: there
 * is no schema for a bounding box, a label or a score anywhere in
 * `app/schemas` or `app/api/schemas.py`.
 *
 * Rather than invent that contract, this component reads `data.detections`
 * defensively and renders only what is actually present, falling back to the
 * tool's own answer text. When the backend defines the payload, the shape can
 * be typed properly in `types/api.ts` and the overlay drawn here.
 * ------------------------------------------------------------------------
 */

interface LooseDetection {
  label?: unknown
  confidence?: unknown
  score?: unknown
}

function readDetections(value: unknown): LooseDetection[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (entry): entry is LooseDetection => typeof entry === 'object' && entry !== null,
  )
}

export function DetectionsResult({ result }: { result: TaskResponse }) {
  const detections = readDetections(result.data.detections)

  const counts = new Map<string, number>()
  for (const detection of detections) {
    const label = typeof detection.label === 'string' ? detection.label : 'unlabelled'
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }

  const confidences = detections
    .map((detection) =>
      typeof detection.confidence === 'number'
        ? detection.confidence
        : typeof detection.score === 'number'
          ? detection.score
          : null,
    )
    .filter((value): value is number => value !== null)

  const meanConfidence =
    confidences.length > 0
      ? confidences.reduce((sum, value) => sum + value, 0) / confidences.length
      : null

  if (detections.length === 0) {
    return (
      <Notice tone="info" title="No detection payload was returned">
        This result declares detections as its output type, but the response
        carried no detection records. The answer above is what the capability
        reported.
      </Notice>
    )
  }

  return (
    <>
      <StatGrid>
        <Stat label="Objects detected" value={detections.length} accent />
        <Stat label="Distinct labels" value={counts.size} />
        {meanConfidence != null ? (
          <Stat label="Mean confidence" value={formatPercent(meanConfidence, 0)} />
        ) : null}
      </StatGrid>

      <Panel title="By label">
        <ul className="sq-classes__list">
          {[...counts.entries()]
            .sort(([, a], [, b]) => b - a)
            .map(([label, count]) => (
              <li key={label} className="sq-classes__row">
                <span className="sq-classes__name">{humanise(label)}</span>
                <span className="sq-classes__share sq-mono">{count}</span>
              </li>
            ))}
        </ul>
      </Panel>
    </>
  )
}
