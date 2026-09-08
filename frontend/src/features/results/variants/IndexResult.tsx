import { Panel, Stat, StatGrid } from '../../../components/ui'
import { RasterViewer } from '../../raster/RasterViewer'
import { ClassBreakdown } from '../parts/ClassBreakdown'
import { DistributionStrip } from '../parts/DistributionStrip'
import { artifactUrl } from '../../../services/satquery'
import { classLabel } from '../../../utils/labels'
import { formatArea, formatIndex, formatPercent } from '../../../utils/format'
import type { TaskResponse } from '../../../types/api'

/**
 * A normalised-difference index result: NDVI, NDWI or NDBI.
 *
 * The raster leads, because the answer to "how healthy is the vegetation" is
 * a picture. The numbers that follow are chosen for this result specifically -
 * the median rather than the mean, the dominant class, the area actually
 * observed - and not from a fixed template applied to every analysis.
 */
export function IndexResult({ result }: { result: TaskResponse }) {
  const { data, statistics, images } = result
  const indexName = data.index ?? 'Index'
  const crs = images[0]?.crs ?? null

  const raster = result.artifacts.find((artifact) => artifact.kind === 'raster')
  const classes = data.classes ?? {}
  const classOrder = Object.keys(classes)

  const dominant = classOrder.reduce<{ key: string; fraction: number } | null>(
    (best, key) => {
      const fraction = classes[key]?.fraction ?? 0
      return !best || fraction > best.fraction ? { key, fraction } : best
    },
    null,
  )

  const observedArea = formatArea(statistics.valid_area_square_units, crs)

  return (
    <>
      {raster ? (
        <Panel bare>
          <div className="sq-result__viewer">
            <RasterViewer
              url={artifactUrl(raster)}
              artifactId={raster.artifact_id}
              indexName={indexName}
              valueLabel={indexName}
              caption={data.formula ? `${data.formula}` : undefined}
            />
          </div>
        </Panel>
      ) : null}

      <StatGrid>
        <Stat
          label={`Median ${indexName}`}
          value={formatIndex(statistics.median)}
          accent
          note={
            statistics.minimum != null && statistics.maximum != null
              ? `range ${formatIndex(statistics.minimum, 2)} to ${formatIndex(
                  statistics.maximum,
                  2,
                )}`
              : undefined
          }
        />

        {dominant ? (
          <Stat
            label="Dominant class"
            value={classLabel(dominant.key)}
            note={`${formatPercent(dominant.fraction)} of valid pixels`}
          />
        ) : null}

        {statistics.valid_area_square_units != null ? (
          <Stat
            label="Area observed"
            value={observedArea.value}
            unit={observedArea.unit}
          />
        ) : (
          <Stat
            label="Valid pixels"
            value={formatPercent(statistics.valid_fraction)}
            note="of the raster"
          />
        )}

        {statistics.valid_area_square_units != null ? (
          <Stat
            label="Coverage"
            value={formatPercent(statistics.valid_fraction)}
            note="pixels that could be computed"
          />
        ) : null}
      </StatGrid>

      <div className="sq-result__split">
        <Panel title="Composition">
          <ClassBreakdown
            classes={classes}
            crs={crs}
            order={classOrder}
            caption={data.interpretation ?? undefined}
          />
        </Panel>

        <Panel title="Spread">
          <DistributionStrip statistics={statistics} label={indexName} />
        </Panel>
      </div>
    </>
  )
}
