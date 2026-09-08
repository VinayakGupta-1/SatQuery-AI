import type { ReactNode, SVGProps } from 'react'

/**
 * One icon system: 24x24, 1.5px stroke, round caps, `currentColor`.
 *
 * Hand-drawn rather than pulled from a library, so every glyph shares one
 * optical weight and the set stays small. Icons are decorative by default and
 * hidden from assistive technology; pass `title` when an icon carries meaning
 * no adjacent text repeats.
 */
export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'children'> {
  /** Rendered size in pixels. The three sizes in use are 14, 16 and 20. */
  size?: number
  title?: string
}

export function Icon({
  size = 16,
  title,
  children,
  ...props
}: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
      {...props}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  )
}
