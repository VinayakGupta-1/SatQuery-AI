import { useEffect, useState } from 'react'
import { Button } from '../../components/ui'
import { formatPercent } from '../../utils/format'
import type { RunState } from '../../context/workspaceContext'

/**
 * The stages the request passes through on the server, in the order the
 * controller runs them (`backend/app/controller/pipeline.py`).
 *
 * These are real stage names, not invented activity. What the browser cannot
 * observe is *when* each one begins - the API is a single synchronous call
 * with no progress channel - so the strip advances on a paced timeline and
 * deliberately claims nothing more than "this is what is happening". No stage
 * is ever ticked off, no timings are reported, and no model reasoning is
 * shown. The authoritative per-stage outcome arrives with the result and is
 * available under "Analysis details".
 */
interface Stage {
  name: string
  /** How long to dwell on the stage before moving on. */
  dwellMs: number
}

const STAGES: Stage[] = [
  { name: 'Understanding the request', dwellMs: 2600 },
  { name: 'Checking imagery against requirements', dwellMs: 2600 },
  { name: 'Selecting a capability', dwellMs: 2600 },
  { name: 'Running the analysis', dwellMs: 2600 },
  { name: 'Preparing the result', dwellMs: 2600 },
]

/**
 * With nothing attached, the server first finds the place and downloads
 * Sentinel imagery for it - the longest stage by far, typically 10 to 45
 * seconds - so the strip says so and lingers there.
 */
const FETCH_STAGES: Stage[] = [
  { name: 'Understanding the request', dwellMs: 2000 },
  { name: 'Finding the place and fetching satellite imagery', dwellMs: 20000 },
  ...STAGES.slice(1),
]

interface AnalysisProgressProps {
  run: RunState
  onCancel: () => void
}

export function AnalysisProgress({ run, onCancel }: AnalysisProgressProps) {
  const [stage, setStage] = useState(0)
  const uploading = run.phase === 'uploading'
  const stages = run.fetching ? FETCH_STAGES : STAGES

  useEffect(() => {
    if (uploading) {
      setStage(0)
      return
    }
    // Hold on the last stage rather than looping: a loop would suggest the
    // work had restarted.
    if (stage >= stages.length - 1) return
    const timer = window.setTimeout(() => setStage(stage + 1), stages[stage].dwellMs)
    return () => window.clearTimeout(timer)
  }, [uploading, stage, stages])

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
