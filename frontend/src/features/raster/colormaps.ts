/**
 * Colour ramps for index and change rasters.
 *
 * Each ramp is chosen to match how the index is read on the ground, and to
 * match the legend colours in `utils/labels.ts`, so the map and the legend
 * never disagree. All three index ramps are diverging around zero, because
 * zero is the meaningful breakpoint for every normalised difference: it is the
 * line between water and land for NDWI, between vegetation and not for NDVI.
 */

export type RampStop = [position: number, r: number, g: number, b: number]

export interface Ramp {
  id: string
  name: string
  /** Stops in 0..1 of the ramp's own domain. */
  stops: RampStop[]
  /** The value the ramp is centred on, in raster units. */
  centre: number
}

/** Brown -> straw -> green. Standard vegetation reading. */
const NDVI_RAMP: Ramp = {
  id: 'ndvi',
  name: 'NDVI',
  centre: 0,
  stops: [
    [0, 40, 62, 92],
    [0.35, 122, 104, 78],
    [0.5, 176, 160, 106],
    [0.68, 138, 168, 92],
    [0.84, 84, 142, 74],
    [1, 32, 92, 52],
  ],
}

/** Sand -> teal -> deep blue. Positive NDWI is water. */
const NDWI_RAMP: Ramp = {
  id: 'ndwi',
  name: 'NDWI',
  centre: 0,
  stops: [
    [0, 132, 116, 84],
    [0.4, 168, 158, 128],
    [0.5, 146, 168, 172],
    [0.68, 84, 148, 184],
    [1, 32, 78, 132],
  ],
}

/** Green -> grey -> amber. Positive NDBI is built-up or bare impervious. */
const NDBI_RAMP: Ramp = {
  id: 'ndbi',
  name: 'NDBI',
  centre: 0,
  stops: [
    [0, 58, 102, 66],
    [0.4, 120, 132, 118],
    [0.5, 150, 150, 148],
    [0.66, 190, 150, 96],
    [1, 176, 104, 54],
  ],
}

/** Loss -> stable -> gain, diverging about zero difference. */
const CHANGE_RAMP: Ramp = {
  id: 'change',
  name: 'Change',
  centre: 0,
  stops: [
    [0, 168, 74, 62],
    [0.32, 204, 132, 118],
    [0.5, 58, 66, 78],
    [0.68, 110, 190, 152],
    [1, 42, 132, 96],
  ],
}

const GREY_RAMP: Ramp = {
  id: 'grey',
  name: 'Greyscale',
  centre: 0,
  stops: [
    [0, 14, 18, 24],
    [1, 236, 240, 245],
  ],
}

export const RAMPS: Record<string, Ramp> = {
  ndvi: NDVI_RAMP,
  ndwi: NDWI_RAMP,
  ndbi: NDBI_RAMP,
  change: CHANGE_RAMP,
  grey: GREY_RAMP,
}

/**
 * Pick the ramp for a result.
 *
 * `indexName` comes from `data.index` and `artifactId` from the artifact being
 * drawn - the change tool emits both a difference raster and a classification
 * raster, and only the first is a continuous index.
 */
export function rampFor(indexName?: string | null, artifactId?: string): Ramp {
  if (artifactId?.includes('change_difference')) return CHANGE_RAMP
  const key = (indexName ?? '').toLowerCase()
  return RAMPS[key] ?? GREY_RAMP
}

function interpolate(ramp: Ramp, t: number): [number, number, number] {
  const clamped = Math.min(1, Math.max(0, t))
  const { stops } = ramp
  for (let index = 1; index < stops.length; index += 1) {
    const [position] = stops[index]
    if (clamped <= position) {
      const [previousPosition, pr, pg, pb] = stops[index - 1]
      const [, r, g, b] = stops[index]
      const span = position - previousPosition || 1
      const local = (clamped - previousPosition) / span
      return [
        pr + (r - pr) * local,
        pg + (g - pg) * local,
        pb + (b - pb) * local,
      ]
    }
  }
  const last = stops[stops.length - 1]
  return [last[1], last[2], last[3]]
}

/**
 * Build a 256-entry lookup table so per-pixel colouring is an array index
 * rather than five branches and three multiplications.
 */
export function buildLookup(ramp: Ramp): Uint8ClampedArray {
  const table = new Uint8ClampedArray(256 * 3)
  for (let index = 0; index < 256; index += 1) {
    const [r, g, b] = interpolate(ramp, index / 255)
    table[index * 3] = r
    table[index * 3 + 1] = g
    table[index * 3 + 2] = b
  }
  return table
}

/** CSS gradient for the legend strip, matching the ramp exactly. */
export function rampGradient(ramp: Ramp): string {
  const stops = ramp.stops.map(
    ([position, r, g, b]) => `rgb(${r} ${g} ${b}) ${(position * 100).toFixed(1)}%`,
  )
  return `linear-gradient(90deg, ${stops.join(', ')})`
}
