import { formatCount, formatIndex } from '../../../utils/format'
import type { ResultStatistics } from '../../../types/api'

interface DistributionStripProps {
  statistics: ResultStatistics
  /** Label for the quantity being summarised, e.g. `NDVI`. */
  label: string
}

/**
 * The distribution of an index, drawn from the percentiles the backend
 * already reports.
 *
 * The tool computes p5, p25, p50, p75 and p95 precisely so a frontend can
 * describe the spread without downloading the band. This is a box plot in the
 * width of a card: the whiskers are p5-p95, the box is the interquartile
 * range, and the tick is the median.
 *
 * The mean is deliberately not the headline. On an index raster a handful of
 * cloud or water pixels drag the mean and leave the median untouched, so the
 * median is what a reader should see first.
 */
export function DistributionStrip({ statistics, label }: DistributionStripProps) {
  const percentiles = statistics.percentiles
  const minimum = statistics.minimum
  const maximum = statistics.maximum

  if (
    !percentiles ||
    minimum == null ||
    maximum == null ||
    percentiles.p5 == null ||
    percentiles.p95 == null
  ) {
    return null
  }

  const low = minimum
  const high = maximum
  const span = high - low || 1
  const place = (value: number) => ((value - low) / span) * 100

  const p5 = place(percentiles.p5)
  const p25 = place(percentiles.p25 ?? percentiles.p5)
  const p50 = place(percentiles.p50 ?? 0)
  const p75 = place(percentiles.p75 ?? percentiles.p95)
  const p95 = place(percentiles.p95)

  return (
    <div className="sq-dist">
      <div className="sq-dist__head">
        <span className="sq-label">{label} distribution</span>
        <span className="sq-dist__median sq-mono">
          median {formatIndex(percentiles.p50)}
        </span>
      </div>

      <div
        className="sq-dist__track"
        role="img"
        aria-label={`${label} ranges from ${formatIndex(minimum)} to ${formatIndex(
          maximum,
        )}. Half of all pixels lie between ${formatIndex(
          percentiles.p25,
        )} and ${formatIndex(percentiles.p75)}, with a median of ${formatIndex(
          percentiles.p50,
        )}.`}
      >
        <span
          className="sq-dist__whisker"
          style={{ left: `${p5}%`, width: `${Math.max(0, p95 - p5)}%` }}
        />
        <span
          className="sq-dist__box"
          style={{ left: `${p25}%`, width: `${Math.max(0.5, p75 - p25)}%` }}
        />
        <span className="sq-dist__tick" style={{ left: `${p50}%` }} />
      </div>

      <div className="sq-dist__scale sq-mono">
        <span>{formatIndex(minimum, 2)}</span>
        <span>{formatIndex(maximum, 2)}</span>
      </div>

      <p className="sq-dist__note">
        Whiskers span the 5th to 95th percentile; the box is the middle half of
        all valid pixels.
      </p>

      <dl className="sq-dist__figures">
        <div>
          <dt>Mean</dt>
          <dd className="sq-mono">{formatIndex(statistics.mean)}</dd>
        </div>
        <div>
          <dt>Std deviation</dt>
          <dd className="sq-mono">{formatIndex(statistics.standard_deviation)}</dd>
        </div>
        <div>
          <dt>5th percentile</dt>
          <dd className="sq-mono">{formatIndex(percentiles.p5)}</dd>
        </div>
        <div>
          <dt>95th percentile</dt>
          <dd className="sq-mono">{formatIndex(percentiles.p95)}</dd>
        </div>
        <div>
          <dt>Valid pixels</dt>
          <dd className="sq-mono">{formatCount(statistics.valid_pixels)}</dd>
        </div>
        <div>
          <dt>Nodata pixels</dt>
          <dd className="sq-mono">{formatCount(statistics.nodata_pixels)}</dd>
        </div>
      </dl>
    </div>
  )
}
