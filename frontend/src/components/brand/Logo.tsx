import './logo.css'

/**
 * The SatQuery mark.
 *
 * A meridian globe with one inclined orbit crossing it and a single satellite
 * node on that orbit. It reads as Earth observation rather than as "AI": no
 * brain, no circuit, no robot. The orbit is the brass accent; the globe is the
 * instrument cyan, so the mark carries the product's two colours and nothing
 * else.
 */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className="sq-logo-mark"
    >
      <circle cx="16" cy="16" r="7.6" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M8.4 16h15.2M16 8.4c3.05 3.3 3.05 12.1 0 15.2M16 8.4c-3.05 3.3-3.05 12.1 0 15.2"
        stroke="currentColor"
        strokeWidth="1"
        opacity=".5"
      />
      <ellipse
        cx="16"
        cy="16"
        rx="13.4"
        ry="5.1"
        stroke="var(--sq-brass)"
        strokeWidth="1.4"
        transform="rotate(-28 16 16)"
      />
      <circle cx="26.3" cy="10.4" r="2.2" fill="var(--sq-brass)" />
    </svg>
  )
}

interface WordmarkProps {
  /** `sm` for the top bar, `lg` for the sign-in panel. */
  size?: 'sm' | 'lg'
  /** Optional line beneath the name. */
  tagline?: string
}

export function Wordmark({ size = 'sm', tagline }: WordmarkProps) {
  return (
    <span className={`sq-wordmark sq-wordmark--${size}`}>
      <LogoMark size={size === 'lg' ? 34 : 24} />
      <span className="sq-wordmark__text">
        <span className="sq-wordmark__name">
          SatQuery<span className="sq-wordmark__suffix">AI</span>
        </span>
        {tagline ? <span className="sq-wordmark__tagline">{tagline}</span> : null}
      </span>
    </span>
  )
}
