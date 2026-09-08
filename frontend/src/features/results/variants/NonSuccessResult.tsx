import { Link } from 'react-router-dom'
import { Button, Notice, Panel } from '../../../components/ui'
import { AlertIcon, CapabilityIcon } from '../../../components/icons'
import { useCapabilities } from '../../../context/capabilitiesContext'
import { useWorkspace } from '../../../context/workspaceContext'
import type { TaskResponse } from '../../../types/api'

/**
 * A run that finished without producing an analysis.
 *
 * This is not an error screen in the usual sense. The backend returns 200 for
 * every one of these: the pipeline completed, and its answer was "no". So the
 * screen explains what stopped it and offers the next move, rather than
 * apologising.
 *
 * Three distinct situations are separated on purpose, because the remedy
 * differs: the imagery was wrong for the task, the request could not be
 * matched to a capability, or the computation itself failed.
 */
export function NonSuccessResult({ result }: { result: TaskResponse }) {
  const { executableTools } = useCapabilities()
  const { setDraft, clearFiles } = useWorkspace()

  const requirements = result.explanation
  const errors = result.validation.errors

  if (result.status === 'validation_error') {
    return (
      <Panel>
        <div className="sq-outcome">
          <div className="sq-outcome__icon sq-outcome__icon--danger">
            <AlertIcon size={20} />
          </div>
          <h2 className="sq-outcome__title">This imagery cannot answer that question</h2>
          <p className="sq-outcome__body">{result.answer}</p>

          {errors.length > 0 ? (
            <ul className="sq-outcome__issues">
              {errors.map((issue) => (
                <li key={`${issue.code}-${issue.message}`}>
                  <span className="sq-outcome__issue-code sq-mono">{issue.code}</span>
                  <span>{issue.message}</span>
                </li>
              ))}
            </ul>
          ) : null}

          <dl className="sq-outcome__requirements">
            {requirements.required_bands.length > 0 ? (
              <div>
                <dt>Bands required</dt>
                <dd className="sq-mono">{requirements.required_bands.join(', ')}</dd>
              </div>
            ) : null}
            <div>
              <dt>Images required</dt>
              <dd className="sq-mono">{requirements.minimum_image_count || 1}</dd>
            </div>
            <div>
              <dt>Images supplied</dt>
              <dd className="sq-mono">{result.images.length}</dd>
            </div>
          </dl>

          <div className="sq-outcome__actions">
            <Link
              to="/"
              className="sq-btn sq-btn--primary"
              onClick={() => {
                clearFiles()
                setDraft(result.query)
              }}
            >
              Try different imagery
            </Link>
            <Link to="/help" className="sq-btn sq-btn--ghost">
              What SatQuery needs
            </Link>
          </div>
        </div>
      </Panel>
    )
  }

  if (result.status === 'needs_clarification') {
    const blocked = result.outcome === 'blocked'
    return (
      <Panel>
        <div className="sq-outcome">
          <div className="sq-outcome__icon sq-outcome__icon--warning">
            <CapabilityIcon size={20} />
          </div>
          <h2 className="sq-outcome__title">
            {blocked
              ? 'That capability is not available in this deployment'
              : 'SatQuery needs a little more to go on'}
          </h2>
          <p className="sq-outcome__body">
            {result.agent?.clarification ?? result.answer}
          </p>

          {executableTools.length > 0 ? (
            <div className="sq-outcome__available">
              <span className="sq-label">Available now</span>
              <ul>
                {executableTools.map((tool) => (
                  <li key={tool.tool_id}>
                    <Link to="/capabilities" className="sq-outcome__capability">
                      <strong>{tool.name}</strong>
                      <span>{tool.description}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="sq-outcome__actions">
            <Link
              to="/"
              className="sq-btn sq-btn--primary"
              onClick={() => setDraft(result.query)}
            >
              Rephrase the question
            </Link>
            <Link to="/capabilities" className="sq-btn sq-btn--ghost">
              Browse capabilities
            </Link>
          </div>
        </div>
      </Panel>
    )
  }

  return (
    <Panel>
      <div className="sq-outcome">
        <div className="sq-outcome__icon sq-outcome__icon--danger">
          <AlertIcon size={20} />
        </div>
        <h2 className="sq-outcome__title">The analysis could not be completed</h2>
        <p className="sq-outcome__body">{result.answer}</p>

        {result.validation.warnings.length > 0 ? (
          <Notice tone="warning" title="Warnings raised before the run">
            <ul className="sq-outcome__issues sq-outcome__issues--plain">
              {result.validation.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </Notice>
        ) : null}

        <div className="sq-outcome__actions">
          <Link
            to="/"
            className="sq-btn sq-btn--primary"
            onClick={() => setDraft(result.query)}
          >
            Try again
          </Link>
          <Button variant="ghost" onClick={() => window.location.reload()}>
            Reload the workspace
          </Button>
        </div>
      </div>
    </Panel>
  )
}
