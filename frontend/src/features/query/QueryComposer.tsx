import { useEffect, useMemo, useRef, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { Button, Checkbox, Notice, Tag, TextField } from '../../components/ui'
import { AttachIcon, ScanIcon, SendIcon } from '../../components/icons'
import { useWorkspace } from '../../context/workspaceContext'
import { useCapabilities } from '../../context/capabilitiesContext'
import { UploadDropzone } from './UploadDropzone'
import { suggestionsFor } from './suggestions'
import { formatCount } from '../../utils/format'

/** Greeting by local time. Small, but it makes the workspace feel occupied. */
function greeting(): string {
  const hour = new Date().getHours()
  if (hour < 5) return 'Good night'
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

interface QueryComposerProps {
  operator: string
  onSubmit: (query: string) => void
}

/**
 * The question box.
 *
 * One input, one action, and everything else folded away until it is needed:
 * the scene toggle appears only with more than one raster staged, the sensor
 * hint lives behind a disclosure, and the dry-run check only offers itself
 * once there is imagery to check.
 */
export function QueryComposer({ operator, onSubmit }: QueryComposerProps) {
  const {
    draft,
    setDraft,
    files,
    addFiles,
    asScene,
    setAsScene,
    sensor,
    setSensor,
    check,
    checking,
    checkResult,
    clearCheck,
  } = useWorkspace()
  const { capabilities } = useCapabilities()

  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const dropRef = useRef<HTMLDivElement | null>(null)

  const usable = files.filter((entry) => !entry.problem)
  const ready = draft.trim().length > 0 && usable.length > 0
  const suggestions = useMemo(() => suggestionsFor(capabilities), [capabilities])

  // Grow the box with the question rather than scrolling inside a fixed one.
  useEffect(() => {
    const node = textareaRef.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${Math.min(node.scrollHeight, 220)}px`
  }, [draft])

  const submit = () => {
    if (!ready) return
    onSubmit(draft.trim())
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    dropRef.current?.classList.remove('sq-composer--dropping')
    if (event.dataTransfer.files.length > 0) addFiles(event.dataTransfer.files)
  }

  return (
    <div
      ref={dropRef}
      className="sq-composer"
      onDragOver={(event) => {
        event.preventDefault()
        dropRef.current?.classList.add('sq-composer--dropping')
      }}
      onDragLeave={(event) => {
        if (!dropRef.current?.contains(event.relatedTarget as Node)) {
          dropRef.current?.classList.remove('sq-composer--dropping')
        }
      }}
      onDrop={onDrop}
    >
      <header className="sq-composer__intro">
        <p className="sq-composer__greeting">
          {greeting()}, {operator}.
        </p>
        <h1 className="sq-composer__heading">What would you like to analyse?</h1>
      </header>

      <div className="sq-composer__box">
        <label className="sq-sr-only" htmlFor="sq-query">
          Your question about the imagery
        </label>
        <textarea
          id="sq-query"
          ref={textareaRef}
          className="sq-composer__input"
          rows={2}
          placeholder="Ask about vegetation, water, built-up land, or what changed between two dates."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault()
              submit()
            }
          }}
        />

        <div className="sq-composer__toolbar">
          <label className="sq-composer__attach" htmlFor="sq-upload-input">
            <AttachIcon size={15} />
            <span>{usable.length > 0 ? 'Add imagery' : 'Attach imagery'}</span>
          </label>

          {usable.length > 0 ? (
            <Tag tone="accent">
              {formatCount(usable.length)} {usable.length === 1 ? 'raster' : 'rasters'}
            </Tag>
          ) : null}

          <div className="sq-composer__toolbar-spacer" />

          {usable.length > 0 ? (
            <Button
              size="sm"
              variant="ghost"
              icon={<ScanIcon size={14} />}
              onClick={() => void check()}
              disabled={checking}
              title="Check the imagery against the request without running the analysis"
            >
              {checking ? 'Checking' : 'Check first'}
            </Button>
          ) : null}

          <Button
            variant="primary"
            icon={<SendIcon size={15} />}
            onClick={submit}
            disabled={!ready}
          >
            Analyse
          </Button>
        </div>
      </div>

      <p className="sq-composer__shortcut">
        {usable.length === 0 ? (
          <>
            Attach a satellite scene to analyse —{' '}
            <span className="sq-mono">
              {(capabilities?.accepted_formats ?? ['.tif', '.jp2']).join(' ')}
            </span>
            . Ordinary photos (JPEG, PNG) cannot be analysed.{' '}
            <Link to="/help" className="sq-composer__where">
              Where do I get imagery?
            </Link>
          </>
        ) : (
          'Press Ctrl + Enter to run.'
        )}
      </p>

      {checkResult ? (
        <Notice
          tone={checkResult.would_execute ? 'success' : 'warning'}
          title={
            checkResult.would_execute
              ? 'This request would run'
              : 'This request would not run yet'
          }
          actions={
            <Button size="sm" variant="ghost" onClick={clearCheck}>
              Dismiss
            </Button>
          }
        >
          {checkResult.would_execute ? (
            <>
              The imagery satisfies the requirements for{' '}
              <strong>{checkResult.selected_tool ?? 'the selected capability'}</strong>.
              Nothing has been computed yet.
            </>
          ) : checkResult.validation.errors.length > 0 ? (
            <ul className="sq-composer__issues">
              {checkResult.validation.errors.map((issue) => (
                <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>
              ))}
            </ul>
          ) : (
            (checkResult.explanation.selection_reason ||
              'The request could not be matched to an available capability.')
          )}
        </Notice>
      ) : null}

      <UploadDropzone variant="inline" />

      {files.length > 1 ? (
        <div className="sq-composer__options">
          <Checkbox
            label="These files are bands of one scene"
            checked={asScene}
            onChange={(event) => setAsScene(event.target.checked)}
          />
          <p className="sq-composer__options-hint">
            Products often ship one file per band. Tick this when B04 and B08 are
            two bands of the same image rather than two separate images.
          </p>
          {asScene ? (
            <div className="sq-composer__sensor">
              <TextField
                label="Sensor (optional)"
                placeholder="sentinel2"
                value={sensor}
                onChange={(event) => setSensor(event.target.value)}
                hint="Helps SatQuery read numeric band names such as B04 and B08."
                autoCapitalize="none"
                spellCheck={false}
              />
            </div>
          ) : null}
        </div>
      ) : null}

      {suggestions.length > 0 && draft.trim().length === 0 ? (
        <div className="sq-composer__suggestions">
          <span className="sq-label">Try</span>
          <ul>
            {suggestions.map((suggestion) => (
              <li key={suggestion.text}>
                <button
                  type="button"
                  className="sq-composer__suggestion"
                  onClick={() => {
                    setDraft(suggestion.text)
                    textareaRef.current?.focus()
                  }}
                >
                  {suggestion.text}
                  {suggestion.images > 1 ? (
                    <span className="sq-composer__suggestion-note">
                      {suggestion.images} images
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
