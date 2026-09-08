import { ExportIcon } from '../../../components/icons'
import { artifactUrl } from '../../../services/satquery'
import type { ArtifactLink } from '../../../types/api'

/**
 * The files a run produced, as downloads.
 *
 * Served through the API rather than from a path, so nothing on the server
 * filesystem is addressable. Each entry keeps the backend's own description,
 * which states the dtype and what nodata means - the information someone
 * opening the file in a GIS actually needs.
 */
export function ArtifactList({ artifacts }: { artifacts: ArtifactLink[] }) {
  if (artifacts.length === 0) return null

  return (
    <ul className="sq-artifacts">
      {artifacts.map((artifact) => (
        <li key={artifact.artifact_id} className="sq-artifacts__item">
          <ExportIcon size={16} className="sq-artifacts__icon" />
          <div className="sq-artifacts__body">
            <span className="sq-artifacts__name">
              {artifact.artifact_id.replace(/_/g, ' ')}
            </span>
            <span className="sq-artifacts__note">{artifact.description}</span>
          </div>
          <a
            className="sq-btn sq-btn--secondary sq-btn--sm"
            href={artifactUrl(artifact)}
            download
          >
            {artifact.format ?? 'Download'}
          </a>
        </li>
      ))}
    </ul>
  )
}
