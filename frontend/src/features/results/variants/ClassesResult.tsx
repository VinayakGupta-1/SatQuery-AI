import { Panel, Stat, StatGrid } from '../../../components/ui'
import { RasterViewer } from '../../raster/RasterViewer'
import { ClassBreakdown } from '../parts/ClassBreakdown'
import { artifactUrl } from '../../../services/satquery'
import { classLabel } from '../../../utils/labels'
import { formatArea, formatPercent } from '../../../utils/format'
import type { TaskResponse } from '../../../types/api'

/**
 * A class map: land cover, or any tool declaring `OutputType.CLASSES`.
 *
 * Driven entirely by `data.classes`, which the API layer normalises onto every
 * response, so this renders whatever class vocabulary the tool used without
 * needing to know it in advance.
 */
export function ClassesResult({ result }: { result: TaskResponse }) {
  const classes = result.data.classes ?? {}
  const crs = result.images[0]?.crs ?? null
  const raster = result.artifacts.find((artifact) => artifact.kind === 'raster')

  const ranked = Object.entries(classes).sort(
    ([, a], [, b]) => (b.fraction ?? 0) - (a.fraction ?? 0),
  )
  const [topKey, top] = ranked[0] ?? []
  const observed = formatArea(result.statistics.valid_area_square_units, crs)

  return (
    <>
      {raster ? (
        <Panel bare>
          <div className="sq-result__viewer">
            <RasterViewer
              url={artifactUrl(raster)}
              artifactId={raster.artifact_id}
              valueLabel="class"
              caption={raster.description}
            />
          </div>
        </Panel>
      ) : null}

      <StatGrid>
        {topKey && top ? (
          <Stat
            label="Largest class"
            value={classLabel(topKey)}
            accent
            note={formatPercent(top.fraction)}
          />
        ) : null}
        <Stat label="Classes found" value={ranked.length} />
        {result.statistics.valid_area_square_units != null ? (
          <Stat label="Area classified" value={observed.value} unit={observed.unit} />
        ) : null}
      </StatGrid>

      <Panel title="Class composition">
        <ClassBreakdown
          classes={classes}
          crs={crs}
          order={ranked.map(([key]) => key)}
        />
      </Panel>
    </>
  )
}
