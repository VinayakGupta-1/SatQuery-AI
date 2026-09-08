import { Link, useNavigate } from 'react-router-dom'
import { IconButton, Notice, StateBlock } from '../../components/ui'
import { SavedIcon, SendIcon, TrashIcon } from '../../components/icons'
import { useWorkspace } from '../../context/workspaceContext'
import { formatRelative } from '../../utils/format'

/**
 * Questions kept for reuse.
 *
 * Stored in this browser, not on the server: the backend has no user model and
 * nowhere to keep them. The screen says so rather than implying a synced
 * library.
 */
export function SavedPage() {
  const navigate = useNavigate()
  const { saved, removeSaved, setDraft } = useWorkspace()

  return (
    <div className="sq-page">
      <header className="sq-page__head">
        <div>
          <h1 className="sq-page__title">Saved queries</h1>
          <p className="sq-page__lede">
            Questions you have kept. Reusing one puts it back in the composer,
            ready for new imagery.
          </p>
        </div>
      </header>

      <Notice tone="info">
        Saved queries are stored in this browser only. The analysis service does
        not keep them.
      </Notice>

      {saved.length === 0 ? (
        <StateBlock
          icon={<SavedIcon size={20} />}
          title="Nothing saved yet"
          body="Save a question from any result to keep it here for the next scene."
          actions={
            <Link to="/" className="sq-btn sq-btn--primary">
              Ask a question
            </Link>
          }
        />
      ) : (
        <ul className="sq-history">
          {saved.map((entry) => (
            <li key={entry.id}>
              <div className="sq-history__row">
                <div className="sq-history__main">
                  <span className="sq-history__query">{entry.text}</span>
                  <span className="sq-history__answer">
                    Saved {formatRelative(entry.savedAt)}
                  </span>
                </div>
                <div className="sq-history__meta">
                  <IconButton
                    label="Use this query"
                    onClick={() => {
                      setDraft(entry.text)
                      navigate('/')
                    }}
                  >
                    <SendIcon size={15} />
                  </IconButton>
                  <IconButton
                    label="Remove from saved"
                    onClick={() => removeSaved(entry.id)}
                  >
                    <TrashIcon size={15} />
                  </IconButton>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
