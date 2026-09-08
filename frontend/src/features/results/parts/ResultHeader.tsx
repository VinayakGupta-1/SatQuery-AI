import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Tag } from '../../../components/ui'
import { AskIcon, CheckIcon, SavedIcon } from '../../../components/icons'
import { STATUS_META } from '../../../utils/labels'
import { formatDuration } from '../../../utils/format'
import { useWorkspace } from '../../../context/workspaceContext'
import type { TaskResponse } from '../../../types/api'

interface ResultHeaderProps {
  result: TaskResponse
  /** Browser-measured round trip, when this result was produced in this tab. */
  durationMs?: number | null
}

/**
 * What was asked, and how it went.
 *
 * The question is the heading, because that is what the user recognises. The
 * status is a single tag rather than a banner: a completed analysis should not
 * announce itself.
 */
export function ResultHeader({ result, durationMs }: ResultHeaderProps) {
  const { saveQuery, saved, setDraft } = useWorkspace()
  const [justSaved, setJustSaved] = useState(false)
  const status = STATUS_META[result.status]
  const alreadySaved = saved.some((entry) => entry.text === result.query.trim())

  return (
    <header className="sq-result__head">
      <div className="sq-result__head-main">
        <div className="sq-result__meta">
          <Tag tone={status.tone}>{status.label}</Tag>
          {result.tool ? <span className="sq-result__tool">{result.tool}</span> : null}
          {durationMs != null ? (
            <span className="sq-result__timing sq-mono" title="Measured in the browser">
              {formatDuration(durationMs)}
            </span>
          ) : null}
        </div>
        <h1 className="sq-result__query">{result.query}</h1>
      </div>

      <div className="sq-result__actions">
        <Button
          size="sm"
          variant="ghost"
          icon={justSaved || alreadySaved ? <CheckIcon size={14} /> : <SavedIcon size={14} />}
          disabled={alreadySaved || justSaved}
          onClick={() => {
            saveQuery(result.query)
            setJustSaved(true)
          }}
        >
          {alreadySaved || justSaved ? 'Saved' : 'Save query'}
        </Button>
        {/* A navigation control is a link, not a button, so it keeps
            middle-click, "open in new tab" and the browser's own affordances. */}
        <Link
          to="/"
          className="sq-btn sq-btn--secondary sq-btn--sm"
          onClick={() => setDraft('')}
        >
          <AskIcon size={14} />
          New query
        </Link>
      </div>
    </header>
  )
}
