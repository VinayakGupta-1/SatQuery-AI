import { artifactUrl } from '../../../services/satquery'
import type { ArtifactLink } from '../../../types/api'

export interface PreviewItem {
  artifact: ArtifactLink
  /** What this picture is, e.g. `Earlier - 2023-11-02` or `Radar (SAR)`. */
  label: string
}

/**
 * Two renderings side by side: before and after, or optical and radar.
 *
 * Used wherever a result was read from two pictures, so the reader sees both
 * of them - the pair is the evidence, and showing only one would hide half of
 * it.
 */
export function PreviewPair({ items, caption }: { items: PreviewItem[]; caption?: string }) {
  if (items.length === 0) return null

  return (
    <figure className="sq-pair">
      <div className="sq-pair__grid">
        {items.map(({ artifact, label }) => (
          <div className="sq-pair__cell" key={artifact.artifact_id}>
            <span className="sq-pair__label sq-label">{label}</span>
            <img
              className="sq-pair__image"
              src={artifactUrl(artifact)}
              alt={`${label}: ${artifact.description || 'rendered preview'}`}
            />
          </div>
        ))}
      </div>
      {caption ? <figcaption className="sq-vqa__caption">{caption}</figcaption> : null}
    </figure>
  )
}
