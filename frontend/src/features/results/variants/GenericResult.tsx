import { Panel, Stat, StatGrid } from '../../../components/ui'
import { RasterViewer } from '../../raster/RasterViewer'
import { ClassBreakdown } from '../parts/ClassBreakdown'
import { artifactUrl } from '../../../services/satquery'
import { humanise } from '../../../utils/labels'
import { formatIndex, formatPercent } from '../../../utils/format'
import type { TaskResponse } from '../../../types/api'

/** Statistics that are already presented elsewhere on the result screen. */
const HANDLED_KEYS = new Set([
  'percentiles',
  'classes',
  'valid_pixels',
  'nodata_pixels',
  'total_pixels',
  'pixel_area_square_units',
])

/**
 * The fallback presentation, and the one used for masks.
 *
 * A tool that declares an output type this frontend has no bespoke view for
 * still gets a real result screen: its raster is drawn, its classes are
 * broken down, and whatever numeric statistics it reported are shown. Nothing
 * is fabricated and nothing is dropped.
 */
export function GenericResult({ result }: { result: TaskResponse }) {
  const raster = result.artifacts.find((artifact) => artifact.kind === 'raster')
  const classes = result.data.classes ?? {}
  const crs = result.images[0]?.crs ?? null

  const numeric = Object.entries(result.statistics).filter(
    ([key, value]) => typeof value === 'number' && !HANDLED_KEYS.has(key),
  ) as [string, number][]

  return (
    <>
      {raster ? (
        <Panel bare>
          <div className="sq-result__viewer">
            <RasterViewer
              url={artifactUrl(raster)}
              artifactId={raster.artifact_id}
              indexName={result.data.index}
              caption={raster.description}
            />
          </div>
        </Panel>
      ) : null}

      {numeric.length > 0 ? (
        <StatGrid>
          {numeric.slice(0, 6).map(([key, value]) => (
            <Stat
              key={key}
              label={humanise(key)}
              value={
                key.includes('fraction')
                  ? formatPercent(value)
                  : formatIndex(value, Number.isInteger(value) ? 0 : 3)
              }
            />
          ))}
        </StatGrid>
      ) : null}

      {Object.keys(classes).length > 0 ? (
        <Panel title="Composition">
          <ClassBreakdown classes={classes} crs={crs} />
        </Panel>
      ) : null}
    </>
  )
}
