/**
 * Turning backend identifiers into the words a person reads.
 *
 * The backend speaks in snake_case ids - `bare_soil_or_built_up`,
 * `needs_clarification`, `tool_selection`. Those are the right names for a
 * contract and the wrong names for a screen. The mapping lives here, once,
 * with a generic fallback so a new backend label degrades to readable text
 * instead of appearing raw.
 */

import type { OutputType, TaskStatus, ToolType } from '../types/api'

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
  classification: 'Classification',
  planning: 'Planning',
  validation: 'Input validation',
  tool_selection: 'Capability selection',
  parameter_configuration: 'Parameter resolution',
  execution: 'Execution',
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
