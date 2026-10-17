import { Panel, Tag } from '../../../components/ui'
import { formatDate, formatLonLat, formatPercent } from '../../../utils/format'
import type { AcquiredScene, AcquisitionReport } from '../../../types/api'

const SOURCE_LABEL: Record<string, string> = {
  geocoded: 'found from the place named in the question',
  'location field': 'from the location you entered',
  'query coordinates': 'from the coordinates in the question',
}

const ROLE_LABEL: Record<string, string> = {
  image: 'Scene',
  before: 'Before',
  after: 'After',
  optical: 'Optical',
  sar: 'Radar',
}

const COLLECTION_LABEL: Record<string, string> = {
  'sentinel-2-l2a': 'Sentinel-2 L2A',
  'sentinel-1-rtc': 'Sentinel-1 RTC',
}

function SceneRow({ scene }: { scene: AcquiredScene }) {
  const facts = [
    scene.platform,
    `${scene.resolution_m} m pixels`,
    scene.area_cloud_fraction != null
      ? `${formatPercent(scene.area_cloud_fraction, 1)} cloud over the area`
      : scene.modality === 'sar'
        ? 'radar, unaffected by cloud'
        : null,
    scene.coverage < 0.999 ? `${formatPercent(scene.coverage, 0)} of the area covered` : null,
  ].filter(Boolean)

  return (
    <li className="sq-acquired__scene">
      <div className="sq-acquired__scene-head">
        <Tag tone={scene.modality === 'sar' ? 'info' : 'accent'}>
          {ROLE_LABEL[scene.role] ?? scene.role}
        </Tag>
        <strong>{COLLECTION_LABEL[scene.collection] ?? scene.collection}</strong>
        <span>{formatDate(scene.acquired)}</span>
      </div>
      <p className="sq-acquired__facts">{facts.join(' · ')}</p>
      <p className="sq-acquired__items sq-mono" title="Catalogue item ids">
        {scene.item_ids.join(', ')}
      </p>
    </li>
  )
}

/**
 * Where the imagery came from, when nobody attached any.
 *
 * An NDVI figure means nothing until the reader knows which place, which day
 * and which scene it describes, so this is shown with the answer rather than
 * folded away: the resolved place (a geocoder can pick the wrong Paris), each
 * scene with its date and the cloud measured over the area itself, and every
 * adjustment SatQuery made along the way.
 */
export function AcquisitionPanel({ report }: { report: AcquisitionReport }) {
  if (report.status !== 'fetched') return null

  return (
    <Panel title="Imagery fetched for this question">
      <div className="sq-acquired">
        {report.place ? (
          <p className="sq-acquired__place">
            <strong>{report.place}</strong>
            {report.place_source ? (
              <span> - {SOURCE_LABEL[report.place_source] ?? report.place_source}</span>
            ) : null}
            {report.bbox_lonlat ? (
              <span className="sq-acquired__bbox sq-mono">
                {formatLonLat([report.bbox_lonlat[0], report.bbox_lonlat[1]])} to{' '}
                {formatLonLat([report.bbox_lonlat[2], report.bbox_lonlat[3]])}
              </span>
            ) : null}
          </p>
        ) : null}

        <ul className="sq-acquired__scenes">
          {report.scenes.map((scene) => (
            <SceneRow key={scene.image_id} scene={scene} />
          ))}
        </ul>

        {report.period ? (
          <p className="sq-acquired__period">Searched {report.period}.</p>
        ) : null}

        {report.notes.length > 0 ? (
          <ul className="sq-acquired__notes">
            {report.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}

        <p className="sq-acquired__attribution">{report.attribution}</p>
      </div>
    </Panel>
  )
}
