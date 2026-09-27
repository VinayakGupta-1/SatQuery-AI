import { Panel, Stat, StatGrid } from '../../../components/ui'
import { RasterViewer } from '../../raster/RasterViewer'
import { ClassBreakdown } from '../parts/ClassBreakdown'
import { PreviewPair, type PreviewItem } from '../parts/PreviewPair'
import { artifactUrl } from '../../../services/satquery'
import { classLabel } from '../../../utils/labels'
import { formatArea, formatDate, formatIndex, formatPercent } from '../../../utils/format'
import type { TaskResponse } from '../../../types/api'

/**
 * A class map: land cover, a SAR water map, or any tool declaring
 * `OutputType.CLASSES`.
 *
 * Driven entirely by `data.classes`, which the API layer normalises onto every
 * response, so this renders whatever class vocabulary the tool used without
 * needing to know it in advance. `data.class_codes` tells the viewer which
 * pixel value is which class, so the map is drawn in the legend's colours.
 */
export function ClassesResult({ result }: { result: TaskResponse }) {
  const { data, statistics } = result
  const classes = data.classes ?? {}
  const crs = result.images[0]?.crs ?? null
  // The class map is the first raster; a SAR result also carries backscatter.
  const raster = result.artifacts.find((artifact) => artifact.kind === 'raster')

  const ranked = Object.entries(classes).sort(
    ([, a], [, b]) => (b.fraction ?? 0) - (a.fraction ?? 0),
  )
  const [topKey, top] = ranked[0] ?? []
  const observed = formatArea(statistics.valid_area_square_units, crs)

  // Fusion labels water by which sensor saw it; it has no single water class.
  const fusion = data.method === 'optical_sar_water_fusion'

  // A water map is read for its water, not for whichever class is largest.
  const water = data.polarisation && !fusion ? classes.water : undefined
  const waterArea = formatArea(water?.area_square_units, crs)

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
              classCodes={data.class_codes}
            />
          </div>
        </Panel>
      ) : null}

      <StatGrid>
        {fusion ? (
          <FusionStats result={result} />
        ) : water ? (
          <>
            <Stat
              label="Open water"
              value={
                water.area_square_units != null
                  ? waterArea.value
                  : formatPercent(water.fraction)
              }
              unit={water.area_square_units != null ? waterArea.unit : undefined}
              accent
              note={`${formatPercent(water.fraction)} of the observed scene`}
            />
            <Stat
              label={`Median ${data.polarisation}`}
              value={formatIndex(statistics.median, 1)}
              unit="dB"
              note={data.speckle_filter ? `speckle filter: ${data.speckle_filter}` : undefined}
            />
          </>
        ) : topKey && top ? (
          <>
            <Stat
              label="Largest class"
              value={classLabel(topKey)}
              accent
              note={formatPercent(top.fraction)}
            />
            <Stat label="Classes found" value={ranked.filter(([, c]) => c.pixels > 0).length} />
          </>
        ) : null}
        {statistics.valid_area_square_units != null ? (
          <Stat label="Area classified" value={observed.value} unit={observed.unit} />
        ) : null}
      </StatGrid>

      <Panel title="Class composition">
        <ClassBreakdown
          classes={classes}
          crs={crs}
          order={ranked.map(([key]) => key)}
          caption={data.interpretation ?? undefined}
        />
        {data.rules && data.rules.length > 0 ? (
          <p className="sq-classes__caption">
            Rules, applied in order: <span className="sq-mono">{data.rules.join(' · ')}</span>
          </p>
        ) : null}
        {fusion && data.optical_rule && data.radar_rule ? (
          <p className="sq-classes__caption">
            Optical water: <span className="sq-mono">{data.optical_rule}</span>
            {data.cloud_mask ? ` (cloud masked with ${data.cloud_mask})` : ''}. Radar water:{' '}
            <span className="sq-mono">{data.radar_rule}</span>.
          </p>
        ) : null}
      </Panel>

      {fusion ? <FusionPictures result={result} /> : null}
    </>
  )
}

/**
 * The fusion headline: how much water either sensor saw, how much of it only
 * radar could see through cloud, and how far the two sensors agree where both
 * could look. Agreement is Cohen's kappa, so chance agreement scores zero.
 */
function FusionStats({ result }: { result: TaskResponse }) {
  const { data, statistics } = result
  const classes = data.classes ?? {}
  const kappa = typeof statistics.kappa === 'number' ? statistics.kappa : null
  const waterFraction = typeof statistics.water_fraction === 'number' ? statistics.water_fraction : null
  const underCloud = classes.water_under_cloud?.fraction ?? 0

  return (
    <>
      <Stat
        label="Water, either sensor"
        value={formatPercent(waterFraction)}
        accent
        note="of the observed scene"
      />
      <Stat
        label="Seen only through cloud"
        value={formatPercent(underCloud)}
        note="radar water the optical image could not see"
      />
      <Stat
        label="Sensor agreement"
        value={kappa != null ? formatIndex(kappa, 2) : '--'}
        unit="κ"
        note={
          data.days_apart == null
            ? 'Cohen’s kappa over pixels both observed'
            : data.days_apart === 0
              ? 'acquired the same day'
              : `acquired ${data.days_apart} day${data.days_apart === 1 ? '' : 's'} apart`
        }
      />
    </>
  )
}

function FusionPictures({ result }: { result: TaskResponse }) {
  const { data, artifacts } = result
  const optical = artifacts.find((artifact) => artifact.artifact_id === 'scene_preview')
  const radar = artifacts.find((artifact) => artifact.artifact_id === 'radar_preview')
  const items: PreviewItem[] = []
  if (optical) {
    items.push({
      artifact: optical,
      label: data.optical_date ? `Optical · ${formatDate(data.optical_date)}` : 'Optical',
    })
  }
  if (radar) {
    items.push({
      artifact: radar,
      label: data.radar_date ? `Radar (SAR) · ${formatDate(data.radar_date)}` : 'Radar (SAR)',
    })
  }
  if (items.length === 0) return null

  return (
    <Panel title="What each sensor saw">
      <PreviewPair items={items} />
    </Panel>
  )
}
