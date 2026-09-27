import { Panel, Tag } from '../../../components/ui'
import { CONFIDENCE_META, factorLabel } from '../../../utils/labels'
import { formatPercent } from '../../../utils/format'
import type { ConfidenceReport } from '../../../types/api'

/**
 * How far the answer can be trusted, and why.
 *
 * The score is the weakest of the measured factors, so the panel shows every
 * factor and marks the one that set the score: "41% because most of the
 * scene was cloud" is something a reader can act on, a bare 41% is not.
 * An answer from a model nobody has benchmarked is shown as unrated, with
 * its measured factors still listed, rather than given an invented number.
 */
export function ConfidencePanel({ report }: { report: ConfidenceReport }) {
  const meta = CONFIDENCE_META[report.level]
  const weakest =
    report.score != null
      ? report.factors.find((factor) => factor.score === report.score)?.name
      : undefined

  return (
    <Panel title="Confidence">
      <div className="sq-confidence">
        <div className="sq-confidence__head">
          <Tag tone={meta.tone}>{meta.label}</Tag>
          {report.score != null ? (
            <span className="sq-confidence__score sq-mono">{formatPercent(report.score, 0)}</span>
          ) : null}
        </div>
        <p className="sq-confidence__basis">{report.basis}</p>

        {report.factors.length > 0 ? (
          <ul className="sq-confidence__factors">
            {report.factors.map((factor) => (
              <li
                key={factor.name}
                className={`sq-confidence__factor${factor.name === weakest ? ' sq-confidence__factor--weakest' : ''}`}
              >
                <div className="sq-confidence__factor-head">
                  <span>{factorLabel(factor.name)}</span>
                  <span className="sq-mono">{formatPercent(factor.score, 0)}</span>
                </div>
                <div
                  className="sq-confidence__bar"
                  role="meter"
                  aria-label={factorLabel(factor.name)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(factor.score * 100)}
                >
                  <span style={{ width: `${Math.round(factor.score * 100)}%` }} />
                </div>
                <p className="sq-confidence__detail">{factor.detail}</p>
              </li>
            ))}
          </ul>
        ) : null}

        <p className="sq-confidence__note">
          The score is the weakest factor. It indicates reliability; it is not a calibrated
          probability.
        </p>
      </div>
    </Panel>
  )
}
