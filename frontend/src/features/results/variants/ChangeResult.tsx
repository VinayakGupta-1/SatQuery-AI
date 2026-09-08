import { useState } from 'react'
import { Notice, Panel, Segmented, Stat, StatGrid } from '../../../components/ui'
import { RasterViewer } from '../../raster/RasterViewer'
import { ClassBreakdown } from '../parts/ClassBreakdown'
import { artifactUrl } from '../../../services/satquery'
import { formatArea, formatDate, formatIndex, formatPercent } from '../../../utils/format'
import type { TaskResponse } from '../../../types/api'

/** Change classes always read loss, stable, gain - never alphabetically. */
const CHANGE_ORDER = ['decrease', 'stable', 'increase']

/**
 * A bi-temporal change result.
 *
 * Two rasters come back: the continuous difference and the thresholded
 * classification. They answer different questions - "how much changed here"
 * and "did this pixel change at all" - so the viewer offers both rather than
 * picking one.
 *
 * The temporal ordering is stated prominently when the backend had to assume
 * it. The sign of every number on this screen depends on that assumption, and
 * a reader is entitled to know when it was a guess.
 */
export function ChangeResult({ result }: { result: TaskResponse }) {
  const { data, statistics, images } = result
  const crs = images[0]?.crs ?? null

  const difference = result.artifacts.find(
    (artifact) => artifact.artifact_id === 'change_difference_raster',
  )
  const classification = result.artifacts.find(
    (artifact) => artifact.artifact_id === 'change_class_raster',
  )

  const [layer, setLayer] = useState<'difference' | 'classes'>('difference')
  const active = layer === 'difference' ? difference : classification
  const assumedOrder = data.temporal_order_source === 'input_order'

  const classes = data.classes ?? {}
  const increase = classes.increase?.fraction ?? 0
  const decrease = classes.decrease?.fraction ?? 0
  const changedArea = formatArea(
    (classes.increase?.area_square_units ?? 0) +
      (classes.decrease?.area_square_units ?? 0),
    crs,
  )
  const hasArea = classes.increase?.area_square_units != null

  return (
    <>
      {assumedOrder ? (
        <Notice tone="warning" title="Date order was assumed">
          {data.note ??
            'Acquisition dates were not available in both rasters, so the upload order was taken as earliest first. The direction of the reported change depends on that.'}
        </Notice>
      ) : null}

      {active ? (
        <Panel bare>
          <div className="sq-result__viewer">
            <div className="sq-result__viewer-bar">
              <Segmented
                label="Change layer"
                value={layer}
                onChange={setLayer}
                options={[
                  { value: 'difference', label: 'Difference' },
                  { value: 'classes', label: 'Classified' },
                ]}
              />
              {data.earlier_date && data.later_date ? (
                <span className="sq-result__dates sq-mono">
                  {formatDate(data.earlier_date)} → {formatDate(data.later_date)}
                </span>
              ) : null}
            </div>

            <RasterViewer
              key={active.artifact_id}
              url={artifactUrl(active)}
              artifactId={active.artifact_id}
              indexName={layer === 'difference' ? 'change' : null}
              valueLabel={layer === 'difference' ? `d${data.index ?? ''}` : 'class'}
              caption={
                layer === 'difference'
                  ? data.formula
                  : '0 nodata · 1 decrease · 2 stable · 3 increase'
              }
            />
          </div>
        </Panel>
      ) : null}

      <StatGrid>
        <Stat
          label="Area changed"
          value={
            hasArea ? changedArea.value : formatPercent(statistics.changed_fraction)
          }
          unit={hasArea ? changedArea.unit : undefined}
          accent
          note={
            hasArea
              ? `${formatPercent(statistics.changed_fraction)} of observed area`
              : 'of pixels valid on both dates'
          }
        />
        <Stat
          label={data.increase_means ?? 'Increase'}
          value={formatPercent(increase)}
          note="of comparable pixels"
        />
        <Stat
          label={data.decrease_means ?? 'Decrease'}
          value={formatPercent(decrease)}
          note="of comparable pixels"
        />
        <Stat
          label="Threshold"
          value={formatIndex(data.threshold, 2)}
          note={data.threshold_description ?? data.threshold_method}
        />
      </StatGrid>

      <Panel title="Change breakdown">
        <ClassBreakdown
          classes={classes}
          crs={crs}
          order={CHANGE_ORDER}
          caption={`Classified from ${data.formula ?? 'the index difference'}. A pixel is only classified where both dates are valid.`}
        />
      </Panel>
    </>
  )
}
