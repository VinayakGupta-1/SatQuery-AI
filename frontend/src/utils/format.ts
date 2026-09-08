/** Presentation helpers. Every number a user reads passes through here. */

/** A signed index value: `0.72`, `-0.13`. */
export function formatIndex(value: number | null | undefined, digits = 3): string {
  if (value == null || !Number.isFinite(value)) return '--'
  return value.toFixed(digits)
}

/** A percentage from a 0..1 fraction. */
export function formatPercent(
  fraction: number | null | undefined,
  digits = 1,
): string {
  if (fraction == null || !Number.isFinite(fraction)) return '--'
  return `${(fraction * 100).toFixed(digits)}%`
}

/** A pixel or object count with thousands separators. */
export function formatCount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '--'
  return value.toLocaleString()
}

/** Compact count for tight spaces: `1.2M`. */
export function formatCompact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '--'
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return '--'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

/**
 * Ground area, in the units of the raster's CRS.
 *
 * The backend reports `area_square_units` rather than square metres, because
 * the unit depends on the CRS and it will not claim metres it cannot prove.
 * That honesty is carried through here: a projected CRS in metres is converted
 * to km2 and labelled, anything else keeps the neutral "units" wording.
 */
export function formatArea(
  squareUnits: number | null | undefined,
  crs?: string | null,
): { value: string; unit: string } {
  if (squareUnits == null || !Number.isFinite(squareUnits)) {
    return { value: '--', unit: '' }
  }

  if (isMetreCrs(crs)) {
    if (squareUnits >= 1e6) {
      return { value: (squareUnits / 1e6).toFixed(2), unit: 'km²' }
    }
    return { value: Math.round(squareUnits).toLocaleString(), unit: 'm²' }
  }

  if (squareUnits >= 1e6) {
    return { value: formatCompact(squareUnits), unit: 'sq. CRS units' }
  }
  return { value: Math.round(squareUnits).toLocaleString(), unit: 'sq. CRS units' }
}

/**
 * One area unit for a whole table.
 *
 * Formatting each row independently puts `892,400 m²` next to `25.05 km²` in
 * the same column, which the eye cannot compare. The unit is chosen once from
 * the largest value and applied to every row.
 */
export function areaFormatter(
  values: (number | null | undefined)[],
  crs?: string | null,
): { format: (value: number | null | undefined) => string; unit: string } {
  const metres = isMetreCrs(crs)
  const largest = values.reduce<number>(
    (max, value) => (value != null && Number.isFinite(value) && value > max ? value : max),
    0,
  )

  if (metres && largest >= 1e6) {
    return {
      unit: 'km²',
      format: (value) =>
        value == null || !Number.isFinite(value) ? '--' : (value / 1e6).toFixed(2),
    }
  }

  const unit = metres ? 'm²' : 'sq. units'
  return {
    unit,
    format: (value) =>
      value == null || !Number.isFinite(value)
        ? '--'
        : Math.round(value).toLocaleString(),
  }
}

/**
 * Whether a CRS string denotes a projected system whose unit is the metre.
 *
 * Geographic CRSs (EPSG:4326 and friends) measure in degrees, where an "area"
 * is not a physical quantity, so those deliberately fall through to the
 * neutral wording above.
 */
export function isMetreCrs(crs: string | null | undefined): boolean {
  if (!crs) return false
  const value = crs.toUpperCase()
  // Geographic CRSs measure in degrees; an area in square degrees is not a
  // physical quantity, so these are excluded before anything else.
  if (/EPSG:\s*(4326|4269|4258|4979)\b/.test(value)) return false
  // UTM zones on WGS 84 are EPSG:326xx (north) and EPSG:327xx (south);
  // 3857 and 3395 are the two Mercators in common use.
  if (/EPSG:\s*(32[67]\d{2}|3857|3395)\b/.test(value)) return true
  return /\bUTM\b|MERCATOR|LAMBERT|ALBERS|STEREOGRAPHIC|TRANSVERSE/.test(value)
}

/** Ground sample distance from the `resolution` pair. */
export function formatResolution(
  resolution: number[] | null | undefined,
  crs?: string | null,
): string {
  if (!resolution || resolution.length < 2) return '--'
  const [x, y] = resolution
  const unit = isMetreCrs(crs) ? 'm' : 'units'
  const round = (value: number) =>
    value >= 1 ? value.toFixed(value % 1 === 0 ? 0 : 1) : value.toPrecision(2)
  return Math.abs(x - y) < 1e-9
    ? `${round(x)} ${unit}`
    : `${round(x)} x ${round(y)} ${unit}`
}

export function formatDimensions(
  width: number | null | undefined,
  height: number | null | undefined,
): string {
  if (!width || !height) return '--'
  return `${width.toLocaleString()} x ${height.toLocaleString()} px`
}

/** `2024-06-14` -> `14 Jun 2024`. Returns the raw string if unparseable. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '--'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

/** A short relative time for history entries: `just now`, `12m ago`. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  if (seconds < 45) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
  if (seconds < 604800) return `${Math.round(seconds / 86400)}d ago`
  return formatDate(iso)
}

/** Round-trip duration, measured in the browser. */
export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds == null || !Number.isFinite(milliseconds)) return '--'
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} s`
  const minutes = Math.floor(milliseconds / 60_000)
  const seconds = Math.round((milliseconds % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}
