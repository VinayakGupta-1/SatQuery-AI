import { useMemo } from 'react'
import { Notice, Panel, Stat, StatGrid } from '../../../components/ui'
import { RasterViewer, type RasterBox } from '../../raster/RasterViewer'
import { artifactUrl } from '../../../services/satquery'
import { areaFormatter, formatArea, formatCount } from '../../../utils/format'
import { classColour, classLabel } from '../../../utils/labels'
import type { Detection, TaskResponse } from '../../../types/api'

/** Outlines beyond this many turn the map into a thicket; the list has them all. */
const MAX_OUTLINES = 40
/** Rows shown in the object list. */
const MAX_ROWS = 12

/**
 * A detection result: discrete objects, each a connected region of one
 * land-cover class, with an extent and an area.
 *
 * The map shows every detected object in its type's colour, with the largest
 * outlined; the numbers below say how many of each type were found and how
 * much ground they cover. Nothing here claims a detection confidence, because
 * the backend reports none: these are measured regions, not model guesses.
 */
export function DetectionsResult({ result }: { result: TaskResponse }) {
  const { data } = result
  const detections: Detection[] = useMemo(() => data.detections ?? [], [data.detections])
  const counts = data.counts ?? {}
  const total = data.detections_total ?? detections.length
  const crs = result.images[0]?.crs ?? null
  const raster = result.artifacts.find((artifact) => artifact.artifact_id === 'detections_raster')

  const boxes: RasterBox[] = useMemo(
    () =>
      detections.slice(0, MAX_OUTLINES).map((detection) => {
        const [x0, y0, x1, y1] = detection.bbox_pixels
        return {
          id: detection.id,
          x0,
          y0,
          x1: x1 + 1,
          y1: y1 + 1,
          colour: classColour(detection.label),
        }
      }),
    [detections],
  )

  const byType = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .sort(([, a], [, b]) => b - a)
  const largest = detections[0]
  const largestArea = formatArea(largest?.area_square_units, crs)
  const area = areaFormatter(
    detections.map((detection) => detection.area_square_units),
    crs,
  )
  const unresolvable = data.unresolvable_targets ?? []

  return (
    <>
      {unresolvable.length > 0 ? (
        <Notice tone="warning" title="Not every object type could be searched for">
          {unresolvable.join(', ')} cannot be resolved at this imagery's resolution:
          individual objects that small need sub-metre imagery and a trained
          detector. The other types you asked for are shown below.
        </Notice>
      ) : null}

      {raster ? (
        <Panel bare>
          <div className="sq-result__viewer">
            <RasterViewer
              url={artifactUrl(raster)}
              artifactId={raster.artifact_id}
              valueLabel="object"
              caption={`Each colour is an object type; the ${Math.min(
                MAX_OUTLINES,
                detections.length,
              )} largest objects are outlined.`}
              classCodes={data.class_codes}
              boxes={boxes}
            />
          </div>
        </Panel>
      ) : null}

      <StatGrid>
        <Stat
          label="Objects found"
          value={formatCount(total)}
          accent
          note={
            data.min_area_pixels != null
              ? `at least ${formatCount(data.min_area_pixels)} px each`
              : undefined
          }
        />
        {largest ? (
          <Stat
            label="Largest"
            value={
              largest.area_square_units != null
                ? largestArea.value
                : `${formatCount(largest.pixels)} px`
            }
            unit={largest.area_square_units != null ? largestArea.unit : undefined}
            note={classLabel(largest.label)}
          />
        ) : null}
        <Stat label="Types found" value={byType.length} />
      </StatGrid>

      {total === 0 ? (
        <Notice tone="info" title="No objects were found">
          No {(data.targets ?? []).map((target) => classLabel(target).toLowerCase()).join(', ') || 'objects'}{' '}
          of at least {formatCount(data.min_area_pixels ?? 1)} pixels were found in
          this scene.
        </Notice>
      ) : (
        <div className="sq-result__split">
          <Panel title="By type">
            <ul className="sq-classes__list">
              {byType.map(([label, count]) => {
                const covered = data.areas_square_units?.[label]
                return (
                  <li key={label} className="sq-classes__row">
                    <span
                      className="sq-classes__swatch"
                      style={{ background: classColour(label) }}
                      aria-hidden="true"
                    />
                    <span className="sq-classes__name">{classLabel(label)}</span>
                    <span className="sq-classes__share sq-mono">{formatCount(count)}</span>
                    <span className="sq-classes__detail sq-mono">
                      {covered != null ? `${area.format(covered)} ${area.unit}` : ''}
                    </span>
                  </li>
                )
              })}
            </ul>
          </Panel>

          <Panel title="Largest objects">
            <ol className="sq-objects">
              {detections.slice(0, MAX_ROWS).map((detection) => (
                <li key={detection.id} className="sq-objects__row">
                  <span className="sq-objects__id sq-mono">#{detection.id}</span>
                  <span
                    className="sq-classes__swatch"
                    style={{ background: classColour(detection.label) }}
                    aria-hidden="true"
                  />
                  <span className="sq-objects__name">{classLabel(detection.label)}</span>
                  <span className="sq-objects__area sq-mono">
                    {detection.area_square_units != null
                      ? `${area.format(detection.area_square_units)} ${area.unit}`
                      : `${formatCount(detection.pixels)} px`}
                  </span>
                  <span className="sq-objects__where sq-mono" title="Centre of the object">
                    {detection.centroid
                      ? `${Math.round(detection.centroid[0])}, ${Math.round(detection.centroid[1])}`
                      : `px ${Math.round(detection.centroid_pixel[0])}, ${Math.round(detection.centroid_pixel[1])}`}
                  </span>
                </li>
              ))}
            </ol>
            {total > MAX_ROWS ? (
              <p className="sq-classes__caption">
                {formatCount(total - MAX_ROWS)} smaller objects are in the downloadable
                object-id raster.
              </p>
            ) : null}
          </Panel>
        </div>
      )}
    </>
  )
}
