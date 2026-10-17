import { useEffect, useState } from 'react'
import { Button } from '../../components/ui'
import { formatPercent } from '../../utils/format'
import type { RunState } from '../../context/workspaceContext'

/**
 * The stages the request passes through on the server, in the order the
 * controller runs them (`backend/app/controller/pipeline.py`).
 *
 * The browser sends a reference with the request and polls
 * `/api/progress/{ref}`, so the strip shows the stage the server has actually
 * reached - and, while imagery is fetched, what the fetcher is doing ("Found
 * Pune", "Downloading 5 bands of the 2026-10-15 scene"). Against a backend that
 * does not report, it falls back to a paced timeline that claims no more than
 * "this is what is happening".
 */
interface Stage {
  key: string
  name: string
  /** How long the fallback timeline dwells on the stage. */
  dwellMs: number
}

const STAGES: Stage[] = [
  { key: 'understand', name: 'Understanding the request', dwellMs: 2600 },
  { key: 'plan', name: 'Planning and choosing a capability', dwellMs: 2600 },
  { key: 'check', name: 'Checking imagery against requirements', dwellMs: 2600 },
  { key: 'run', name: 'Running the analysis', dwellMs: 2600 },
  { key: 'result', name: 'Preparing the result', dwellMs: 2600 },
]

/**
 * With nothing attached, the server first finds the place and downloads
 * Sentinel imagery for it - the longest stage by far, typically 10 to 45
 * seconds.
 */
const FETCH_STAGES: Stage[] = [
  STAGES[0],
  { key: 'fetch', name: 'Finding the place and fetching satellite imagery', dwellMs: 20000 },
  ...STAGES.slice(1),
]

/** The step under way once the server has reported finishing `stage`. */
function currentStep(stage: string, status: string, fetching: boolean): string {
  switch (stage) {
    case 'understanding':
      return fetching ? 'fetch' : 'plan'
    case 'acquisition':
      return status === 'running' ? 'fetch' : 'plan'
    case 'adaptation':
    case 'classification':
    case 'planning':
    case 'input_requirements':
      return 'plan'
    case 'tool_selection':
      return 'check'
    case 'validation':
    case 'parameter_configuration':
      return 'run'
    default:
      return 'result'
  }
}

interface AnalysisProgressProps {
  run: RunState
  onCancel: () => void
}

export function AnalysisProgress({ run, onCancel }: AnalysisProgressProps) {
  const [paced, setPaced] = useState(0)
  const uploading = run.phase === 'uploading'
  const stages = run.fetching ? FETCH_STAGES : STAGES
  const reported = run.progress

  useEffect(() => {
    if (uploading) {
      setPaced(0)
      return
    }
    // The paced timeline only runs while the server has reported nothing.
    // Hold on the last stage rather than looping: a loop would suggest the
    // work had restarted.
    if (reported || paced >= stages.length - 1) return
    const timer = window.setTimeout(() => setPaced(paced + 1), stages[paced].dwellMs)
    return () => window.clearTimeout(timer)
  }, [uploading, paced, stages, reported])

  const stage = reported
    ? Math.max(
        0,
        stages.findIndex(
          (entry) => entry.key === currentStep(reported.stage, reported.status, run.fetching),
        ),
      )
    : paced
  const detail =
    reported && reported.stage === 'acquisition' && reported.status === 'running'
      ? reported.detail
      : ''

  const label = uploading
    ? run.fetching
      ? 'Sending the question'
      : 'Sending imagery'
    : stages[stage].name

  return (
    <section className="sq-analysing" aria-busy="true">
      <div className="sq-analysing__frame">
        {/* The scanning swath. One line, one grid, one orbit - the visual
            vocabulary of the product rather than a generic spinner. */}
        <div className="sq-analysing__grid" aria-hidden="true" />
        <div className="sq-analysing__sweep sq-progress-motion" aria-hidden="true" />
        <div className="sq-analysing__orbit" aria-hidden="true">
          <span className="sq-analysing__satellite sq-progress-motion" />
        </div>

        <div className="sq-analysing__readout">
          <span className="sq-label">Analysing</span>
          <p className="sq-analysing__query">{run.query}</p>
        </div>
      </div>

      <div className="sq-analysing__status">
        <p className="sq-analysing__stage" aria-live="polite">
          {label}
          {uploading ? (
            <span className="sq-analysing__percent sq-mono">
              {formatPercent(run.uploaded, 0)}
            </span>
          ) : null}
        </p>
        {detail ? <p className="sq-analysing__detail">{detail}</p> : null}

        {uploading ? (
          <div
            className="sq-analysing__bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(run.uploaded * 100)}
            aria-label="Imagery upload"
          >
            <span style={{ width: `${Math.max(2, run.uploaded * 100)}%` }} />
          </div>
        ) : (
          <ol className="sq-analysing__stages">
            {stages.map(({ name }, index) => (
              <li
                key={name}
                className={[
                  'sq-analysing__step',
                  index < stage ? 'sq-analysing__step--past' : '',
                  index === stage ? 'sq-analysing__step--current' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                <span className="sq-analysing__step-dot" aria-hidden="true" />
                <span className="sq-analysing__step-label">{name}</span>
              </li>
            ))}
          </ol>
        )}

        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </section>
  )
}
