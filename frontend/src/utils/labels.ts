/**
 * Turning backend identifiers into the words a person reads.
 *
 * The backend speaks in snake_case ids - `bare_soil_or_built_up`,
 * `needs_clarification`, `tool_selection`. Those are the right names for a
 * contract and the wrong names for a screen. The mapping lives here, once,
 * with a generic fallback so a new backend label degrades to readable text
 * instead of appearing raw.
 */

import type { ConfidenceReport, Engine, OutputType, TaskStatus, ToolType } from '../types/api'

/** `bare_soil_or_built_up` -> `Bare soil or built up`. */
export function humanise(value: string): string {
  const text = value.replace(/[_-]+/g, ' ').trim()
  if (!text) return ''
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Class labels produced by the index and change tools. */
const CLASS_LABELS: Record<string, string> = {
  // NDVI
  water_or_non_vegetated: 'Water or non-vegetated',
  bare_soil_or_built_up: 'Bare soil or built-up',
  sparse_vegetation: 'Sparse vegetation',
  moderate_vegetation: 'Moderate vegetation',
  dense_vegetation: 'Dense vegetation',
  // NDWI
  non_water: 'Not water',
  possible_water: 'Possible water',
  water: 'Water',
  // NDBI
  non_built_up: 'Not built-up',
  possible_built_up: 'Possible built-up',
  built_up: 'Built-up',
  // Change detection
  increase: 'Increase',
  stable: 'Stable',
  decrease: 'Decrease',
  // Land cover
  bare_soil: 'Bare soil',
  bare_or_built_up: 'Bare or built-up',
  // Object detection
  water_body: 'Water body',
  vegetation_patch: 'Vegetation patch',
  built_up_cluster: 'Built-up cluster',
  bare_land_patch: 'Bare land patch',
  bare_or_built_up_patch: 'Bare or built-up patch',
  // Optical + SAR fusion
  water_both: 'Water, both sensors',
  water_radar_only: 'Water, radar only',
  water_optical_only: 'Water, optical only',
  water_under_cloud: 'Water under cloud',
  land: 'Land',
}

/** Change classes always read loss, stable, gain - never alphabetically. */
export const CHANGE_ORDER = ['decrease', 'stable', 'increase']

/** The codes the change tool writes into its classification raster. */
export const CHANGE_CODES: Record<string, string> = { 1: 'decrease', 2: 'stable', 3: 'increase' }

/** What a task id is called when the question's reading is shown back. */
const TASK_LABELS: Record<string, string> = {
  ndvi: 'Vegetation (NDVI)',
  ndwi: 'Water (NDWI)',
  ndbi: 'Built-up land (NDBI)',
  flood_mapping: 'Flood mapping',
  sar_analysis: 'Radar water mapping',
  optical_sar_fusion: 'Optical + SAR fusion',
  change_detection: 'Change detection',
  change_vqa: 'A question about change',
  image_captioning: 'Scene description',
  image_analysis: 'A question about the image',
  object_detection: 'Object detection',
  segmentation: 'Land-cover segmentation',
  classification: 'Land-cover classification',
}

export function taskLabel(key: string): string {
  return TASK_LABELS[key] ?? humanise(key)
}

/** `optical+sar` -> `Optical + SAR`. */
export function modalityLabel(value: string): string {
  return value
    .split('+')
    .map((part) => (part.toLowerCase() === 'sar' ? 'SAR' : humanise(part)))
    .join(' + ')
}

export function classLabel(key: string): string {
  return CLASS_LABELS[key] ?? humanise(key)
}

/**
 * The colour a class is drawn in, in both the legend and the raster overlay.
 *
 * Chosen so the colour carries the meaning: vegetation classes are green,
 * water blue, built-up amber. A class with no established meaning falls back
 * to a neutral slate rather than to an arbitrary hue.
 */
const CLASS_COLOURS: Record<string, string> = {
  water_or_non_vegetated: '#4a86b8',
  bare_soil_or_built_up: '#a08a6c',
  sparse_vegetation: '#8fae62',
  moderate_vegetation: '#6ea05f',
  dense_vegetation: '#3f7f4c',
  non_water: '#5c6a7a',
  possible_water: '#6fa3c6',
  water: '#3c72a4',
  non_built_up: '#5c6a7a',
  possible_built_up: '#c9a45c',
  built_up: '#b8763f',
  increase: '#56b98d',
  stable: '#4a5666',
  decrease: '#d97a6d',
  bare_soil: '#b39b72',
  bare_or_built_up: '#a08a6c',
  water_body: '#3c72a4',
  vegetation_patch: '#4f8f55',
  built_up_cluster: '#b8763f',
  bare_land_patch: '#b39b72',
  bare_or_built_up_patch: '#a08a6c',
  // Fusion: the blues darken with how many sensors confirm the water.
  water_both: '#2f6496',
  water_radar_only: '#6fa3c6',
  water_optical_only: '#8a9fd6',
  water_under_cloud: '#8fd0e2',
  land: '#4a5666',
}

export function classColour(key: string): string {
  return CLASS_COLOURS[key] ?? '#5c6a7a'
}

/** How a status is announced, and which semantic colour it takes. */
export const STATUS_META: Record<
  TaskStatus,
  { label: string; tone: 'success' | 'warning' | 'danger' | 'info' }
> = {
  success: { label: 'Complete', tone: 'success' },
  needs_clarification: { label: 'Needs input', tone: 'warning' },
  validation_error: { label: 'Imagery rejected', tone: 'danger' },
  execution_error: { label: 'Analysis failed', tone: 'danger' },
}

/** Pipeline stage names, for the advanced disclosure. */
const STAGE_LABELS: Record<string, string> = {
  understanding: 'Understanding',
  adaptation: 'Imagery adaptation',
  classification: 'Classification',
  planning: 'Planning',
  input_requirements: 'Input requirements',
  validation: 'Input validation',
  tool_selection: 'Capability selection',
  parameter_configuration: 'Parameter resolution',
  execution: 'Execution',
  result_integration: 'Result integration',
}

export function stageLabel(key: string): string {
  return STAGE_LABELS[key] ?? humanise(key)
}

/** Whether a stage status reads as reached, refused or never got there. */
export function stageTone(value: string): 'ok' | 'refused' | 'skipped' {
  const normalised = value.toLowerCase()
  if (['not_reached', 'unrecognised', 'unknown'].includes(normalised)) return 'skipped'
  if (
    ['rejected', 'failed', 'blocked', 'invalid', 'needs_input', 'error'].includes(
      normalised,
    )
  ) {
    return 'refused'
  }
  return 'ok'
}

/** Human names for tool families, used to group the capability catalogue. */
export const TOOL_TYPE_LABELS: Record<ToolType, string> = {
  index: 'Spectral indices',
  change_detection: 'Change analysis',
  object_detection: 'Detection',
  classification: 'Classification',
  segmentation: 'Segmentation',
  vqa: 'Visual question answering',
  sar_analysis: 'SAR analysis',
  fusion: 'Optical + SAR fusion',
  captioning: 'Captioning and grounding',
}

/**
 * The two sides of the hybrid core, and the route that uses both.
 *
 * Said on every answer, because "computed" and "read by a model" deserve
 * different degrees of trust and the reader should never have to guess which
 * one they are looking at.
 */
export const ENGINE_META: Record<
  Engine,
  { label: string; tone: 'success' | 'info' | 'accent'; description: string }
> = {
  deterministic: {
    label: 'Deterministic engine',
    tone: 'success',
    description: 'Computed from the pixels by exact arithmetic. Reproducible to the bit.',
  },
  vlm: {
    label: 'Vision-language model',
    tone: 'info',
    description:
      "A vision-language model's reading of a rendered picture of the scene, not a measurement.",
  },
  hybrid: {
    label: 'Measured, then described',
    tone: 'accent',
    description:
      'Change was measured deterministically first; a vision-language model then described it with those numbers in hand.',
  },
}

/** How each confidence level is announced. */
export const CONFIDENCE_META: Record<
  ConfidenceReport['level'],
  { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }
> = {
  high: { label: 'High confidence', tone: 'success' },
  medium: { label: 'Medium confidence', tone: 'warning' },
  low: { label: 'Low confidence', tone: 'danger' },
  unrated: { label: 'Unrated', tone: 'neutral' },
}

/** Confidence factor names, as a reader would say them. */
const FACTOR_LABELS: Record<string, string> = {
  interpretation: 'Question interpretation',
  coverage: 'Observed coverage',
  agreement: 'Sensor agreement',
  model_accuracy: 'Model benchmark accuracy',
}

export function factorLabel(name: string): string {
  return FACTOR_LABELS[name] ?? humanise(name)
}

/** What a result of each output type is called in the interface. */
export const OUTPUT_TYPE_LABELS: Record<OutputType, string> = {
  raster_index: 'Index raster',
  change_map: 'Change map',
  classes: 'Class map',
  detections: 'Detections',
  mask: 'Mask',
  text: 'Answer',
}

/** Band names, for the imagery summary. */
export function bandLabel(band: string): string {
  const known: Record<string, string> = {
    red: 'Red',
    green: 'Green',
    blue: 'Blue',
    nir: 'NIR',
    swir: 'SWIR',
    swir1: 'SWIR 1',
    swir2: 'SWIR 2',
    coastal: 'Coastal',
    pan: 'Panchromatic',
    vv: 'VV',
    vh: 'VH',
  }
  return known[band.toLowerCase()] ?? band.toUpperCase()
}
