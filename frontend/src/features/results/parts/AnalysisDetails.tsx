import { Definition, Definitions, Disclosure, Tag } from '../../../components/ui'
import { InfoIcon } from '../../../components/icons'
import { stageLabel, stageTone } from '../../../utils/labels'
import { formatDuration, formatPercent } from '../../../utils/format'
import type { TaskResponse } from '../../../types/api'

interface AnalysisDetailsProps {
  result: TaskResponse
  durationMs?: number | null
}

/**
 * The audit trail, one click away.
 *
 * SatQuery's design point is that a controlled pipeline can explain itself:
 * which capability was selected and why, what the imagery had to satisfy, what
 * parameters were resolved, and how far each stage got. All of that is in the
 * response already - this panel surfaces it without letting it dominate the
 * answer.
 *
 * What is *not* shown here, deliberately: the understanding layer's own
 * narration. `agent.reasoning` is a model's internal account of its choice and
 * is not presented to the user. What the guard refused is shown, because a
 * refusal is a fact about the system rather than a rationalisation.
 */
export function AnalysisDetails({ result, durationMs }: AnalysisDetailsProps) {
  const { explanation, agent } = result
  const stages = Object.entries(explanation.stage_status)
  const parameters = Object.entries(explanation.resolved_parameters)

  return (
    <Disclosure icon={<InfoIcon size={15} />} summary="Analysis details">
      <div className="sq-details">
        <section className="sq-details__block">
          <h4 className="sq-label">Decision</h4>
          <Definitions>
            <Definition term="Task">
              {explanation.understood_task ?? 'Not determined'}
            </Definition>
            <Definition term="Category">{explanation.task_category}</Definition>
            <Definition term="Capability">
              {result.tool ?? 'None selected'}
              {result.tool_version ? (
                <span className="sq-details__version sq-mono">
                  {' '}
                  v{result.tool_version}
                </span>
              ) : null}
            </Definition>
            {explanation.selection_reason ? (
              <Definition term="Reason">{explanation.selection_reason}</Definition>
            ) : null}
            <Definition term="Confidence">
              {formatPercent(explanation.selection_confidence, 0)}
            </Definition>
            {explanation.alternatives.length > 0 ? (
              <Definition term="Alternatives">
                {explanation.alternatives.join(', ')}
              </Definition>
            ) : null}
          </Definitions>
        </section>

        {explanation.plan_steps.length > 0 ? (
          <section className="sq-details__block">
            <h4 className="sq-label">Plan</h4>
            <ol className="sq-details__steps">
              {explanation.plan_steps.map((step, index) => (
                <li key={`${index}-${step}`}>{step}</li>
              ))}
            </ol>
          </section>
        ) : null}

        <section className="sq-details__block">
          <h4 className="sq-label">Input requirements</h4>
          <Definitions>
            <Definition term="Bands">
              {explanation.required_bands.length > 0
                ? explanation.required_bands.join(', ')
                : 'None specified'}
            </Definition>
            <Definition term="Minimum images">
              {explanation.minimum_image_count || 1}
            </Definition>
            <Definition term="Validation">
              {result.validation.valid ? 'Passed' : 'Refused'}
            </Definition>
          </Definitions>
        </section>

        {parameters.length > 0 ? (
          <section className="sq-details__block">
            <h4 className="sq-label">Resolved parameters</h4>
            <Definitions>
              {parameters.map(([key, value]) => (
                <Definition term={key} key={key}>
                  <span className="sq-mono">
                    {value === null || value === undefined
                      ? '--'
                      : typeof value === 'object'
                        ? JSON.stringify(value)
                        : String(value)}
                  </span>
                </Definition>
              ))}
            </Definitions>
          </section>
        ) : null}

        {stages.length > 0 ? (
          <section className="sq-details__block">
            <h4 className="sq-label">Pipeline stages</h4>
            <ul className="sq-details__stages">
              {stages.map(([stage, status]) => (
                <li key={stage} className={`sq-details__stage sq-details__stage--${stageTone(status)}`}>
                  <span className="sq-details__stage-dot" aria-hidden="true" />
                  <span className="sq-details__stage-name">{stageLabel(stage)}</span>
                  <span className="sq-details__stage-status sq-mono">{status}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {agent ? (
          <section className="sq-details__block">
            <h4 className="sq-label">Understanding layer</h4>
            <Definitions>
              <Definition term="Provider">{agent.provider}</Definition>
              {agent.proposed_tool ? (
                <Definition term="Proposed">{agent.proposed_tool}</Definition>
              ) : null}
              {agent.rejected_tools.length > 0 ? (
                <Definition term="Refused by registry">
                  <span className="sq-details__refused">
                    {agent.rejected_tools.join(', ')}
                  </span>
                </Definition>
              ) : null}
              {agent.rejected_parameters.length > 0 ? (
                <Definition term="Refused parameters">
                  <span className="sq-details__refused">
                    {agent.rejected_parameters.join(', ')}
                  </span>
                </Definition>
              ) : null}
            </Definitions>
            {agent.notes.length > 0 ? (
              <ul className="sq-details__notes">
                {agent.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}

        <section className="sq-details__block">
          <h4 className="sq-label">Run</h4>
          <Definitions>
            <Definition term="Task id">
              <span className="sq-mono">{result.task_id}</span>
            </Definition>
            <Definition term="Outcome">
              <Tag tone={result.status === 'success' ? 'success' : 'warning'}>
                {result.outcome}
              </Tag>
            </Definition>
            {durationMs != null ? (
              <Definition term="Round trip">
                {formatDuration(durationMs)}
                <span className="sq-details__hint"> measured in the browser</span>
              </Definition>
            ) : null}
          </Definitions>
        </section>

        {result.evidence.length > 0 ? (
          <section className="sq-details__block">
            <h4 className="sq-label">Evidence</h4>
            <ul className="sq-details__evidence">
              {result.evidence.map((item, index) => (
                <li key={`${item.source}-${index}`}>
                  <span className="sq-details__evidence-source">{item.source}</span>
                  <span>{item.description}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </Disclosure>
  )
}
