import { classColour, classLabel } from '../../../utils/labels'
import { areaFormatter, formatCount, formatPercent } from '../../../utils/format'
import type { ClassSummary } from '../../../types/api'

interface ClassBreakdownProps {
  classes: Record<string, ClassSummary>
  /** CRS of the source raster, so areas can be labelled honestly. */
  crs?: string | null
  /** Order the classes are listed in. Defaults to the backend's own order. */
  order?: string[]
  caption?: string
}

/**
 * The class composition of a result: one stacked bar, then the numbers.
 *
 * The bar is the fastest read - it says at a glance that a scene is two thirds
 * dense vegetation - and the rows below carry the precision. Colours match the
 * legend used everywhere else for the same class, so the eye can move between
 * the bar, the list and the raster without relearning anything.
 */
export function ClassBreakdown({ classes, crs, order, caption }: ClassBreakdownProps) {
  const keys = order ?? Object.keys(classes)
  const entries = keys
    .filter((key) => key in classes)
    .map((key) => ({ key, ...classes[key] }))

  const total = entries.reduce((sum, entry) => sum + entry.fraction, 0)
  if (entries.length === 0 || total <= 0) return null

  const area = areaFormatter(
    entries.map((entry) => entry.area_square_units),
    crs,
  )

  return (
    <div className="sq-classes">
      <div
        className="sq-classes__bar"
        role="img"
        aria-label={entries
          .map((entry) => `${classLabel(entry.key)} ${formatPercent(entry.fraction)}`)
          .join(', ')}
      >
        {entries.map((entry, index) =>
          entry.fraction > 0 ? (
            <span
              key={entry.key}
              className="sq-classes__segment"
              style={{
                width: `${(entry.fraction / total) * 100}%`,
                background: classColour(entry.key),
                // A short stagger so the bar assembles rather than appearing.
                animationDelay: `${index * 60}ms`,
              }}
            />
          ) : null,
        )}
      </div>

      <ul className="sq-classes__list">
        {entries.map((entry) => {
          return (
            <li key={entry.key} className="sq-classes__row">
              <span
                className="sq-classes__swatch"
                style={{ background: classColour(entry.key) }}
                aria-hidden="true"
              />
              <span className="sq-classes__name">{classLabel(entry.key)}</span>
              <span className="sq-classes__share sq-mono">
                {formatPercent(entry.fraction)}
              </span>
              <span className="sq-classes__detail sq-mono">
                {entry.area_square_units != null
                  ? `${area.format(entry.area_square_units)} ${area.unit}`
                  : `${formatCount(entry.pixels)} px`}
              </span>
            </li>
          )
        })}
      </ul>

      {caption ? <p className="sq-classes__caption">{caption}</p> : null}
    </div>
  )
}
