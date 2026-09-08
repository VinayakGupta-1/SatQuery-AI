/**
 * Earth textures, generated in the browser from real coastline data.
 *
 * There is no bitmap of the Earth in this repository. Instead the Natural
 * Earth 110m land outlines that ship with the `world-atlas` package are
 * projected equirectangularly onto a canvas and shaded, which gives real
 * continents - the right coastlines, the right Himalaya, the right Sahara -
 * with no binary asset, no network request at runtime, and no licence to
 * track. It also means the globe still renders when the machine is offline,
 * which matters for a demo.
 *
 * Three maps are produced:
 *   `albedo`   - ocean and land colour, biome-shaded by latitude and climate
 *   `specular` - white ocean, black land, so only water carries a highlight
 *   `clouds`   - fractal value noise, banded to sit where cloud belts sit
 */

import * as THREE from 'three'
import { feature } from 'topojson-client'
import landTopology from 'world-atlas/land-110m.json'
import type { Topology, GeometryCollection } from 'topojson-specification'

type Ring = [number, number][]

/** Equirectangular projection onto a `width` x `height` canvas. */
function project(
  lon: number,
  lat: number,
  width: number,
  height: number,
): [number, number] {
  return [((lon + 180) / 360) * width, ((90 - lat) / 180) * height]
}

/** Every land ring in the 110m dataset, as lon/lat pairs. */
function landRings(): Ring[] {
  const topology = landTopology as unknown as Topology<{
    land: GeometryCollection
  }>
  // `land` is a TopoJSON GeometryCollection, so `feature` always returns a
  // GeoJSON FeatureCollection here.
  const collection = feature(topology, topology.objects.land)
  const rings: Ring[] = []

  const pushPolygon = (polygon: number[][][]) => {
    for (const ring of polygon) rings.push(ring as Ring)
  }

  for (const item of collection.features) {
    const shape = item.geometry
    if (!shape) continue
    if (shape.type === 'Polygon') pushPolygon(shape.coordinates)
    else if (shape.type === 'MultiPolygon') shape.coordinates.forEach(pushPolygon)
  }
  return rings
}

function tracePath(
  context: CanvasRenderingContext2D,
  rings: Ring[],
  width: number,
  height: number,
): void {
  context.beginPath()
  for (const ring of rings) {
    if (ring.length < 2) continue
    ring.forEach(([lon, lat], index) => {
      const [x, y] = project(lon, lat, width, height)
      if (index === 0) context.moveTo(x, y)
      else context.lineTo(x, y)
    })
    context.closePath()
  }
}

/* -------------------------------------------------------------------------- */
/* Value noise                                                                */
/* -------------------------------------------------------------------------- */

/** Deterministic hash so the same globe is drawn on every load. */
function hash(x: number, y: number, seed: number): number {
  const n = Math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453
  return n - Math.floor(n)
}

function smooth(t: number): number {
  return t * t * (3 - 2 * t)
}

function valueNoise(x: number, y: number, seed: number): number {
  const xi = Math.floor(x)
  const yi = Math.floor(y)
  const xf = smooth(x - xi)
  const yf = smooth(y - yi)
  const a = hash(xi, yi, seed)
  const b = hash(xi + 1, yi, seed)
  const c = hash(xi, yi + 1, seed)
  const d = hash(xi + 1, yi + 1, seed)
  return (a * (1 - xf) + b * xf) * (1 - yf) + (c * (1 - xf) + d * xf) * yf
}

/** Fractal Brownian motion: several octaves of value noise. */
function fbm(x: number, y: number, octaves: number, seed: number): number {
  let value = 0
  let amplitude = 0.5
  let frequency = 1
  let total = 0
  for (let octave = 0; octave < octaves; octave += 1) {
    value += amplitude * valueNoise(x * frequency, y * frequency, seed + octave)
    total += amplitude
    amplitude *= 0.5
    frequency *= 2
  }
  return value / total
}

/**
 * A pre-computed noise field, sampled bilinearly.
 *
 * Evaluating five octaves of value noise per pixel over a 2048x1024 texture is
 * around thirty million transcendental calls, which locks the main thread for
 * over a second on the one screen where a stall is most visible. The field is
 * therefore computed at a fraction of the resolution and interpolated: the
 * noise it stands in for is smooth at this scale, so nothing is lost, and the
 * cost drops by more than an order of magnitude.
 */
interface NoiseField {
  width: number
  height: number
  values: Float32Array
}

function buildField(
  width: number,
  height: number,
  scaleX: number,
  scaleY: number,
  octaves: number,
  seed: number,
): NoiseField {
  const values = new Float32Array(width * height)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      values[y * width + x] = fbm(
        (x / width) * scaleX,
        (y / height) * scaleY,
        octaves,
        seed,
      )
    }
  }
  return { width, height, values }
}

/** Bilinear sample of a field at normalised coordinates, wrapping in x. */
function sampleField(field: NoiseField, u: number, v: number): number {
  const { width, height, values } = field
  const fx = u * (width - 1)
  const fy = v * (height - 1)
  const x0 = Math.floor(fx)
  const y0 = Math.floor(fy)
  const x1 = (x0 + 1) % width
  const y1 = Math.min(y0 + 1, height - 1)
  const tx = fx - x0
  const ty = fy - y0

  const a = values[y0 * width + x0]
  const b = values[y0 * width + x1]
  const c = values[y1 * width + x0]
  const d = values[y1 * width + x1]
  return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
}

/* -------------------------------------------------------------------------- */
/* Colour                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Land colour by latitude: ice, tundra, boreal forest, temperate, the arid
 * belts around 25 degrees, savanna, equatorial forest.
 *
 * Defined as anchors that are *interpolated* rather than as bands that are
 * switched between. Hard thresholds draw visible stripes across every
 * continent; a gradient plus a noise-driven jitter on the latitude reads as
 * climate.
 */
const BIOMES: { lat: number; colour: [number, number, number] }[] = [
  { lat: 0, colour: [56, 86, 54] }, // equatorial forest
  { lat: 14, colour: [110, 112, 70] }, // savanna
  { lat: 25, colour: [158, 140, 100] }, // arid belt
  { lat: 38, colour: [98, 106, 70] }, // temperate
  { lat: 52, colour: [68, 88, 64] }, // boreal forest
  { lat: 70, colour: [124, 130, 120] }, // tundra
  { lat: 83, colour: [198, 205, 212] }, // permanent ice
]

function landColour(lat: number, variation: number): [number, number, number] {
  // Push the latitude around so biome boundaries follow an irregular line
  // rather than a parallel. Damped towards the poles by cos(lat): an
  // equirectangular map squeezes longitude to nothing there, so a constant
  // jitter would draw spokes radiating from the pole.
  const damping = Math.cos((lat * Math.PI) / 180)
  const absolute = Math.min(90, Math.abs(lat) + (variation - 0.5) * 14 * damping)

  let lower = BIOMES[0]
  let upper = BIOMES[BIOMES.length - 1]
  for (let index = 1; index < BIOMES.length; index += 1) {
    if (absolute <= BIOMES[index].lat) {
      lower = BIOMES[index - 1]
      upper = BIOMES[index]
      break
    }
  }

  const span = upper.lat - lower.lat || 1
  const t = Math.min(1, Math.max(0, (absolute - lower.lat) / span))
  const shade = 0.88 + variation * 0.26

  return [0, 1, 2].map((channel) => {
    const value = lower.colour[channel] + (upper.colour[channel] - lower.colour[channel]) * t
    return Math.min(255, value * shade)
  }) as [number, number, number]
}

/** Ocean colour: deep blue, turning colder and greyer towards the poles. */
function oceanColour(lat: number, variation: number): [number, number, number] {
  const absolute = Math.abs(lat)
  const polar = Math.min(1, Math.max(0, (absolute - 55) / 35))
  const depth = 0.92 + variation * 0.18
  const r = (13 + polar * 30) * depth
  const g = (42 + polar * 42) * depth
  const b = (86 + polar * 36) * depth
  return [r, g, b]
}

/* -------------------------------------------------------------------------- */
/* Texture builders                                                           */
/* -------------------------------------------------------------------------- */

function createCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

/**
 * Albedo map: ocean, land, coastal shelf and polar ice.
 *
 * The land mask is rasterised once with the canvas 2D path API, read back, and
 * then used to tint each pixel. Doing the shading per-pixel rather than with
 * fills is what produces coastal shelves and biome gradients instead of flat
 * silhouettes.
 */
export function buildAlbedoTexture(width = 2048): THREE.CanvasTexture {
  const height = width / 2
  const canvas = createCanvas(width, height)
  // The albedo pass reads the canvas back twice (the land mask and its blurred
  // copy), which is exactly the case `willReadFrequently` exists for.
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) throw new Error('Canvas 2D is unavailable.')

  const rings = landRings()

  // 1. Rasterise the land mask.
  context.fillStyle = '#000'
  context.fillRect(0, 0, width, height)
  context.fillStyle = '#fff'
  tracePath(context, rings, width, height)
  context.fill('evenodd')
  const mask = context.getImageData(0, 0, width, height)

  // 2. A blurred copy of the same mask gives the continental shelf: the
  //    lighter water that hugs every coast on a real satellite mosaic.
  context.filter = 'blur(6px)'
  context.drawImage(canvas, 0, 0)
  context.filter = 'none'
  const shelf = context.getImageData(0, 0, width, height)

  // 3. Shade.
  const output = context.createImageData(width, height)
  const variationField = buildField(256, 128, 42, 21, 4, 11)

  for (let y = 0; y < height; y += 1) {
    const lat = 90 - (y / height) * 180
    const v = y / height
    for (let x = 0; x < width; x += 1) {
      const index = (y * width + x) * 4
      const isLand = mask.data[index] > 127
      const nearness = shelf.data[index] / 255

      const variation = sampleField(variationField, x / width, v)

      let colour: [number, number, number]
      if (isLand) {
        colour = landColour(lat, variation)
        // Darken a narrow band just inside the coast so land meets water with
        // an edge rather than a hard cut.
        if (nearness < 0.94) {
          const edge = 0.72 + nearness * 0.28
          colour = [colour[0] * edge, colour[1] * edge, colour[2] * edge]
        }
      } else {
        colour = oceanColour(lat, variation)
        if (nearness > 0.02) {
          // Shelf water: lift towards a teal.
          const lift = Math.min(1, nearness * 1.5)
          colour = [
            colour[0] + lift * 26,
            colour[1] + lift * 52,
            colour[2] + lift * 44,
          ]
        }
      }

      output.data[index] = colour[0]
      output.data[index + 1] = colour[1]
      output.data[index + 2] = colour[2]
      output.data[index + 3] = 255
    }
  }

  context.putImageData(output, 0, 0)

  // 4. Sea ice, drawn last as soft caps over whatever is beneath. Kept faint
  //    and shallow: a bright cap reads as a spotlight on the globe.
  const cap = (top: number, bottom: number, strength: number) => {
    const gradient = context.createLinearGradient(0, top, 0, bottom)
    gradient.addColorStop(0, `rgba(226,233,240,${strength})`)
    gradient.addColorStop(0.5, `rgba(214,224,234,${strength * 0.45})`)
    gradient.addColorStop(1, 'rgba(214,224,234,0)')
    context.fillStyle = gradient
    context.fillRect(0, Math.min(top, bottom), width, Math.abs(bottom - top))
  }
  // The Arctic is sea ice and reaches further; the Antarctic land ice is
  // already drawn by the biome ramp, so its cap only softens the coast.
  cap(0, height * 0.05, 0.72)
  cap(height, height * 0.96, 0.42)

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.anisotropy = 4
  return texture
}

/** Specular map: white over water, black over land. */
export function buildSpecularTexture(width = 1024): THREE.CanvasTexture {
  const height = width / 2
  const canvas = createCanvas(width, height)
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas 2D is unavailable.')

  context.fillStyle = '#b9c8d4'
  context.fillRect(0, 0, width, height)
  context.fillStyle = '#0b0d10'
  tracePath(context, landRings(), width, height)
  context.fill('evenodd')

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.NoColorSpace
  return texture
}

/**
 * Cloud map: fractal noise, weighted by latitude.
 *
 * Real cloud cover is banded - dense at the equator and along the mid-latitude
 * storm tracks, sparse over the subtropical highs. Weighting the noise by that
 * profile is the difference between "clouds" and "static".
 */
export function buildCloudTexture(width = 1024): THREE.CanvasTexture {
  const height = width / 2
  const canvas = createCanvas(width, height)
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas 2D is unavailable.')

  const image = context.createImageData(width, height)
  const field = buildField(384, 224, 46, 34, 5, 31)

  for (let y = 0; y < height; y += 1) {
    const lat = 90 - (y / height) * 180
    const absolute = Math.abs(lat)
    const v = y / height
    // Intertropical convergence zone and the two storm tracks. Both are kept
    // narrow: broad bands project into visible rings around the poles.
    const equatorial = Math.exp(-((absolute - 4) ** 2) / 150)
    const stormTrack = Math.exp(-((absolute - 52) ** 2) / 260)
    const band = 0.2 + equatorial * 0.5 + stormTrack * 0.32

    for (let x = 0; x < width; x += 1) {
      const index = (y * width + x) * 4
      // Stretch the noise zonally: weather systems are wider than they are
      // tall. Fine enough that individual systems read as systems.
      const value = sampleField(field, x / width, v)
      // A high floor keeps the clear sky genuinely clear: partial coverage
      // everywhere reads as a dirty lens rather than as weather.
      const density = Math.max(0, value * band - 0.19) * 6.5
      const alpha = Math.min(1, density) * 240

      image.data[index] = 255
      image.data[index + 1] = 255
      image.data[index + 2] = 255
      image.data[index + 3] = alpha
    }
  }

  context.putImageData(image, 0, 0)

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}
