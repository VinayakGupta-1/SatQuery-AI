import {
  useId,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'
import { AlertIcon, CheckIcon, ChevronIcon, InfoIcon } from '../icons'
import './ui.css'

/* ========================================================================== */
/* Button                                                                     */
/* ========================================================================== */

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  block?: boolean
  /** Rendered before the label. */
  icon?: ReactNode
}

export function Button({
  variant = 'secondary',
  size = 'md',
  block = false,
  icon,
  children,
  className = '',
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={[
        'sq-btn',
        `sq-btn--${variant}`,
        size !== 'md' ? `sq-btn--${size}` : '',
        block ? 'sq-btn--block' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...props}
    >
      {icon}
      {children}
    </button>
  )
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required: an icon-only control must still announce itself. */
  label: string
  size?: 'sm' | 'md'
  outlined?: boolean
  active?: boolean
  /** Show the label in a tooltip on hover and focus. */
  tooltip?: boolean
}

export function IconButton({
  label,
  size = 'md',
  outlined = false,
  active = false,
  tooltip = true,
  children,
  className = '',
  type = 'button',
  ...props
}: IconButtonProps) {
  const button = (
    <button
      type={type}
      aria-label={label}
      aria-pressed={active ? true : undefined}
      className={[
        'sq-iconbtn',
        size === 'sm' ? 'sq-iconbtn--sm' : '',
        outlined ? 'sq-iconbtn--outlined' : '',
        active ? 'sq-iconbtn--active' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...props}
    >
      {children}
    </button>
  )

  if (!tooltip) return button
  return (
    <span className="sq-tip">
      {button}
      <span className="sq-tip__bubble" role="presentation">
        {label}
      </span>
    </span>
  )
}

/* ========================================================================== */
/* Panel                                                                      */
/* ========================================================================== */

export interface PanelProps {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  variant?: 'default' | 'raised' | 'glass'
  /** Remove the body padding, for a panel whose child manages its own. */
  bare?: boolean
  tight?: boolean
  className?: string
  id?: string
}

export function Panel({
  title,
  actions,
  children,
  variant = 'default',
  bare = false,
  tight = false,
  className = '',
  id,
}: PanelProps) {
  return (
    <section
      id={id}
      className={[
        'sq-panel',
        variant !== 'default' ? `sq-panel--${variant}` : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {title || actions ? (
        <header className="sq-panel__header">
          {typeof title === 'string' ? (
            <h2 className="sq-panel__title">{title}</h2>
          ) : (
            title
          )}
          {actions ? <div style={{ display: 'flex', gap: 8 }}>{actions}</div> : null}
        </header>
      ) : null}
      {bare ? (
        children
      ) : (
        <div className={`sq-panel__body${tight ? ' sq-panel__body--tight' : ''}`}>
          {children}
        </div>
      )}
    </section>
  )
}

/* ========================================================================== */
/* Form fields                                                                */
/* ========================================================================== */

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string | null
  hint?: string
  /** Render an element inside the trailing edge of the field. */
  trailing?: ReactNode
}

export function TextField({
  label,
  error,
  hint,
  trailing,
  id,
  className = '',
  ...props
}: TextFieldProps) {
  const generated = useId()
  const fieldId = id ?? generated
  const errorId = `${fieldId}-error`
  const hintId = `${fieldId}-hint`

  return (
    <div className="sq-field">
      <label className="sq-field__label" htmlFor={fieldId}>
        {label}
      </label>
      <div style={{ position: 'relative' }}>
        <input
          id={fieldId}
          className={`sq-input ${className}`}
          aria-invalid={error ? true : undefined}
          aria-describedby={
            [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ') ||
            undefined
          }
          style={trailing ? { paddingRight: 40 } : undefined}
          {...props}
        />
        {trailing ? (
          <span
            style={{
              position: 'absolute',
              right: 4,
              top: '50%',
              transform: 'translateY(-50%)',
            }}
          >
            {trailing}
          </span>
        ) : null}
      </div>
      {hint && !error ? (
        <span className="sq-field__hint" id={hintId}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span className="sq-field__error" id={errorId} role="alert">
          <AlertIcon size={13} />
          {error}
        </span>
      ) : null}
    </div>
  )
}

export interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string
  hideLabel?: boolean
}

export function TextArea({ label, hideLabel, id, className = '', ...props }: TextAreaProps) {
  const generated = useId()
  const fieldId = id ?? generated
  return (
    <div className="sq-field">
      <label className={hideLabel ? 'sq-sr-only' : 'sq-field__label'} htmlFor={fieldId}>
        {label}
      </label>
      <textarea id={fieldId} className={`sq-textarea ${className}`} {...props} />
    </div>
  )
}

export interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
}

export function Checkbox({ label, className = '', ...props }: CheckboxProps) {
  return (
    <label className={`sq-check ${className}`}>
      <input type="checkbox" {...props} />
      <span className="sq-check__box" aria-hidden="true">
        <CheckIcon size={11} />
      </span>
      {label}
    </label>
  )
}

/* ========================================================================== */
/* Tag                                                                        */
/* ========================================================================== */

export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'accent'

export function Tag({
  tone = 'neutral',
  children,
  title,
}: {
  tone?: Tone
  children: ReactNode
  title?: string
}) {
  return (
    <span className={`sq-tag sq-tag--${tone}`} title={title}>
      {children}
    </span>
  )
}

/* ========================================================================== */
/* Statistics                                                                 */
/* ========================================================================== */

export interface StatProps {
  label: string
  value: ReactNode
  unit?: string
  note?: string
  accent?: boolean
}

export function Stat({ label, value, unit, note, accent }: StatProps) {
  return (
    <div className="sq-stat">
      <span className="sq-stat__label">{label}</span>
      <span className={`sq-stat__value${accent ? ' sq-stat__value--accent' : ''}`}>
        {value}
        {unit ? <span className="sq-stat__unit">{unit}</span> : null}
      </span>
      {note ? <span className="sq-stat__note">{note}</span> : null}
    </div>
  )
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="sq-stats">{children}</div>
}

/* ========================================================================== */
/* Disclosure - the progressive-disclosure primitive                          */
/* ========================================================================== */

export interface DisclosureProps {
  summary: ReactNode
  children: ReactNode
  defaultOpen?: boolean
  icon?: ReactNode
  /** Notified when the panel opens or closes, for lazily loading its content. */
  onOpenChange?: (open: boolean) => void
}

export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  icon,
  onOpenChange,
}: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen)
  const panelId = useId()

  return (
    <div className="sq-disclosure">
      <button
        type="button"
        className="sq-disclosure__trigger"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          setOpen((value) => {
            onOpenChange?.(!value)
            return !value
          })
        }}
      >
        {icon}
        <span>{summary}</span>
        <ChevronIcon size={14} className="sq-disclosure__chevron" />
      </button>
      {open ? (
        <div className="sq-disclosure__panel" id={panelId}>
          {children}
        </div>
      ) : null}
    </div>
  )
}

/** Definition list used inside disclosures for technical detail. */
export function Definitions({ children }: { children: ReactNode }) {
  return <dl className="sq-defs">{children}</dl>
}

export function Definition({ term, children }: { term: string; children: ReactNode }) {
  return (
    <>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </>
  )
}

/* ========================================================================== */
/* States                                                                     */
/* ========================================================================== */

export interface StateProps {
  icon?: ReactNode
  tone?: 'neutral' | 'danger' | 'warning'
  title: string
  body?: ReactNode
  actions?: ReactNode
}

export function StateBlock({ icon, tone = 'neutral', title, body, actions }: StateProps) {
  return (
    <div className="sq-state sq-rise">
      {icon ? (
        <div
          className={`sq-state__icon${tone !== 'neutral' ? ` sq-state__icon--${tone}` : ''}`}
        >
          {icon}
        </div>
      ) : null}
      <h3 className="sq-state__title">{title}</h3>
      {body ? <div className="sq-state__body">{body}</div> : null}
      {actions ? <div className="sq-state__actions">{actions}</div> : null}
    </div>
  )
}

export function Skeleton({
  height = 16,
  width = '100%',
  radius,
}: {
  height?: number | string
  width?: number | string
  radius?: number
}) {
  return (
    <div
      className="sq-skeleton"
      style={{ height, width, borderRadius: radius }}
      aria-hidden="true"
    />
  )
}

/* ========================================================================== */
/* Notice                                                                     */
/* ========================================================================== */

export function Notice({
  tone = 'info',
  title,
  children,
  actions,
}: {
  tone?: 'info' | 'success' | 'warning' | 'danger'
  title?: string
  children: ReactNode
  actions?: ReactNode
}) {
  const Glyph = tone === 'info' || tone === 'success' ? InfoIcon : AlertIcon
  return (
    <div className={`sq-notice sq-notice--${tone}`} role={tone === 'danger' ? 'alert' : undefined}>
      <Glyph size={16} className="sq-notice__icon" />
      <div className="sq-notice__body">
        {title ? <div className="sq-notice__title">{title}</div> : null}
        <div>{children}</div>
        {actions ? (
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            {actions}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/* ========================================================================== */
/* Segmented control                                                          */
/* ========================================================================== */

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
  label: string
}) {
  return (
    <div className="sq-segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="sq-segmented__option"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

/** Wrap any element to give it a hover/focus tooltip. */
export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="sq-tip">
      {children}
      <span className="sq-tip__bubble" role="presentation">
        {text}
      </span>
    </span>
  )
}
