/**
 * TypeScript mirrors of the backend's public response models.
 *
 * Every type here corresponds one-to-one with a Pydantic model in
 * `backend/app/api/schemas.py`. Nothing is invented: if a field is not in the
 * backend contract it is not in this file. Fields the backend declares as
 * `| None` are declared `| null` here, because FastAPI serialises them as JSON
 * null rather than omitting them.
 */

/** `app.api.schemas.TaskStatus` - the four states a frontend switches on. */
export type TaskStatus =
  | 'success'
  | 'needs_clarification'
  | 'validation_error'
  | 'execution_error'

/** `app.registry.registry.OutputType` - what shape the result takes. */
export type OutputType =
  | 'raster_index'
  | 'change_map'
  | 'classes'
  | 'detections'
  | 'mask'
  | 'text'

/** `app.registry.registry.ToolType`. */
export type ToolType =
  | 'index'
  | 'vqa'
  | 'segmentation'
  | 'object_detection'
  | 'change_detection'
  | 'classification'
  | 'sar_analysis'
  | 'fusion'
  | 'captioning'

/**
 * `app.registry.registry.Engine` - which side of the hybrid core answers:
 * exact arithmetic over the pixels, a vision-language model reading a
 * rendering, or change measured first and then described by the model.
 */
export type Engine = 'deterministic' | 'vlm' | 'hybrid'

export interface ToolSummary {
  tool_id: string
  name: string
  description: string
  tool_type: ToolType
  version: string
  output_type: OutputType
  supported_modalities: string[]
  required_bands: string[]
  min_images: number
  max_images: number
  requires_temporal_pair: boolean
  /** Parameter name -> declared type, e.g. `{ red_band: 'str' }`. */
  parameters: Record<string, string>
  enabled: boolean
  engine: Engine
  /**
   * False when the tool cannot run in this deployment: no implementation is
   * bound, or the bound one is switched off.
   */
  implemented: boolean
  /** True when an implementation is bound, even if it is switched off. */
  bound: boolean
  /** Why `implemented` is false, phrased for an operator; null otherwise. */
  availability_note: string | null
}

export interface ImageSummary {
  id: string
  filename: string
  width: number | null
  height: number | null
  band_count: number | null
  dtype: string | null
  nodata: number | null
  crs: string | null
  /** GDAL geotransform: [origin_x, pixel_w, row_rot, origin_y, col_rot, pixel_h]. */
  transform: number[] | null
  /** Ground sample distance [x, y] in CRS units. */
  resolution: number[] | null
  /** [min_x, min_y, max_x, max_y] in CRS units. */
  bounds: number[] | null
  modality: string | null
  sensor: string | null
  bands: string[]
  acquisition_date: string | null
  /** The footprint as [west, south, east, north] in degrees, when transformable. */
  bounds_lonlat: number[] | null
}

/** `app.api.schemas.UnderstandingOut` - what the question was read as. */
export interface Understanding {
  intent: string | null
  /** Place names as written. Reported, never geocoded. */
  locations: string[]
  /** The area of interest, in words. */
  area: string | null
  /** The period the question names, in words. */
  period: string | null
  metrics: string[]
  /** What the sentence says about the sensor. */
  query_modality: string | null
  /** What the uploaded imagery actually is. */
  imagery_modality: string | null
}

export interface ValidationIssue {
  code: string
  message: string
  field: string | null
}

export interface ValidationReport {
  valid: boolean
  errors: ValidationIssue[]
  warnings: string[]
}

export interface ArtifactLink {
  artifact_id: string
  kind: string
  format: string | null
  description: string
  /** Server-relative, e.g. `/api/tasks/<task_id>/artifacts/<artifact_id>`. */
  url: string
}

/** The auditable trail: why the system did what it did. */
export interface Explanation {
  understood_task: string | null
  task_category: string
  plan_steps: string[]
  required_bands: string[]
  minimum_image_count: number
  selected_tool: string | null
  selection_reason: string
  selection_confidence: number
  alternatives: string[]
  resolved_parameters: Record<string, unknown>
  /** Stage name -> status, e.g. `{ validation: 'valid' }`. */
  stage_status: Record<string, string>
}

/** What the understanding layer proposed, and what the guard allowed. */
export interface AgentPlan {
  provider: string
  task: string | null
  operation: string | null
  proposed_tool: string | null
  confidence: number
  clarification: string | null
  reasoning: string
  rejected_tools: string[]
  rejected_parameters: string[]
  notes: string[]
}

export interface Evidence {
  source: string
  description: string
  confidence: number | null
}

/** Where a finding lies. Every key is optional: a tool reports what it can. */
export interface FindingLocation {
  /** A 3x3 compass sector, e.g. `north-west` or `centre`. */
  sector?: string
  /** True when the class spans nearly the whole scene and has no one place. */
  widespread?: boolean
  /** [longitude, latitude] in degrees. */
  centroid_lonlat?: [number, number]
  /** [column, row] in source pixels. */
  centroid_pixel?: [number, number]
  /** A model-proposed region: [x0, y0, x1, y1] as fractions of the picture. */
  box_fraction?: [number, number, number, number]
}

/** `app.schemas.results.Finding` - one grounded part of the answer. */
export interface Finding {
  title: string
  detail: string
  location: FindingLocation | null
}

/** One measured ingredient of the confidence score. */
export interface ConfidenceFactor {
  /** `interpretation`, `coverage`, `agreement` or `model_accuracy`. */
  name: string
  score: number
  detail: string
}

/**
 * `app.schemas.results.ConfidenceReport`. The score is the weakest factor,
 * so it always traces to one measurement. `unrated` means a model wrote the
 * answer and nobody has benchmarked that model: no number is invented.
 */
export interface ConfidenceReport {
  score: number | null
  level: 'high' | 'medium' | 'low' | 'unrated'
  basis: string
  factors: ConfidenceFactor[]
}

/** A step a tool took inside one execution. */
export interface TraceStep {
  name: string
  detail: string
  duration_ms: number
}

/** One pipeline stage as it actually ran. */
export interface TraceEvent {
  stage: string
  status: string
  detail: string
  duration_ms: number
  steps: TraceStep[]
}

/**
 * Statistics reported by the index and change tools.
 *
 * The backend builds this dictionary dynamically, so it is typed as a loose
 * record with the keys that are actually produced named for convenience.
 * Every field is optional because a tool that computed nothing reports the
 * empty summary rather than zeros.
 */
export interface ResultStatistics {
  minimum?: number | null
  maximum?: number | null
  mean?: number | null
  median?: number | null
  standard_deviation?: number | null
  percentiles?: Record<string, number>
  valid_pixels?: number
  nodata_pixels?: number
  total_pixels?: number
  valid_fraction?: number
  pixel_area_square_units?: number
  valid_area_square_units?: number
  /** Change detection only. */
  changed_pixels?: number
  changed_fraction?: number
  [key: string]: unknown
}

/** One entry of `data.classes`: a labelled range or change class. */
export interface ClassSummary {
  pixels: number
  fraction: number
  area_square_units?: number
}

/**
 * One detected object. Mirrors the record built by `_record` in
 * `backend/app/tools/detection/tool.py`.
 */
export interface Detection {
  /** 1 is the largest object; ids match the object-id raster. */
  id: number
  label: string
  pixels: number
  /** Inclusive source-pixel indices: [first column, first row, last column, last row]. */
  bbox_pixels: [number, number, number, number]
  /** [column, row] of the centre of mass, in source pixels. */
  centroid_pixel: [number, number]
  /** [min_x, min_y, max_x, max_y] in the raster CRS, when georeferenced. */
  bbox?: [number, number, number, number]
  /** [x, y] in the raster CRS, when georeferenced. */
  centroid?: [number, number]
  area_square_units?: number
}

/** A region the captioning model outlined, placed back on the raster. */
export interface CaptionRegion {
  label: string
  /** [x0, y0, x1, y1] as fractions of the picture, origin top-left. */
  box_fraction: [number, number, number, number]
  /** Inclusive source-pixel indices. */
  bbox_pixels: [number, number, number, number]
  /** In the raster CRS, when georeferenced. */
  bbox?: [number, number, number, number]
  centre_lonlat?: [number, number]
}

/**
 * The tool-specific `data` block. The keys present depend on which tool ran;
 * `classes` is normalised onto every response by the API layer.
 */
export interface ResultData {
  classes?: Record<string, ClassSummary>
  /** Class rasters: pixel value -> class key, e.g. `{ "1": "water" }`. */
  class_codes?: Record<string, string>
  /** Land cover: the rules applied, in order. */
  rules?: string[]
  swir_available?: boolean
  /** Object detection. */
  detections?: Detection[]
  detections_total?: number
  detections_returned?: number
  counts?: Record<string, number>
  areas_square_units?: Record<string, number>
  min_area_pixels?: number
  connectivity?: number
  targets?: string[]
  unresolvable_targets?: string[]
  classification_rules?: string[]
  /** SAR water mapping and SAR change detection. */
  polarisation?: string
  input_units?: string
  speckle_filter?: string
  /** The vision-language model core: VQA, captioning, change-VQA. */
  question?: string
  answer?: string
  model?: string
  provider?: string
  rendering?: string
  rendering_description?: string
  notice?: string
  /** VQA over an optical and a SAR image together. */
  cross_modal?: boolean
  /** Captioning. */
  caption?: string
  regions?: CaptionRegion[]
  notes?: string[]
  /** Change-VQA: the deterministic measurement the model was given. */
  measured?: Record<string, unknown>
  /** Optical + SAR fusion. */
  optical_rule?: string
  radar_rule?: string
  cloud_mask?: string | null
  optical_date?: string | null
  radar_date?: string | null
  days_apart?: number | null
  /** Index tools and change detection. */
  index?: string
  formula?: string
  interpretation?: string
  positive_band?: string
  negative_band?: string
  /** Change detection. */
  method?: string
  index_formula?: string
  threshold?: number
  threshold_description?: string
  threshold_method?: string
  increase_means?: string
  decrease_means?: string
  temporal_order_source?: string
  earlier_date?: string | null
  later_date?: string | null
  note?: string
  [key: string]: unknown
}

export interface TaskResponse {
  task_id: string
  result_id: string
  query: string
  status: TaskStatus
  /** The precise internal reason, e.g. `rejected`, `blocked`, `needs_input`. */
  outcome: string
  answer: string
  task: string | null
  tool: string | null
  tool_version: string | null
  output_type: OutputType | null
  agent: AgentPlan | null
  images: ImageSummary[]
  validation: ValidationReport
  explanation: Explanation
  statistics: ResultStatistics
  data: ResultData
  artifacts: ArtifactLink[]
  evidence: Evidence[]
  /** The weakest measured confidence factor; null when unrated. */
  confidence: number | null
  /** Which engine answered. */
  route: Engine
  understood: Understanding
  /** The answer broken into grounded parts: what, how much, where. */
  findings: Finding[]
  confidence_report: ConfidenceReport | null
  /** Every pipeline stage as it ran, timed, with the tool's own steps. */
  trace: TraceEvent[]
  /** Where the imagery came from, when SatQuery fetched it; null for uploads. */
  acquisition: AcquisitionReport | null
}

/** `app.schemas.acquisition.AcquiredScene` - one scene SatQuery downloaded. */
export interface AcquiredScene {
  image_id: string
  /** `image`, `before`, `after`, `optical` or `sar`. */
  role: string
  collection: string
  sensor: string
  modality: string
  platform: string | null
  /** Catalogue items; more than one when adjacent tiles were mosaicked. */
  item_ids: string[]
  acquired: string
  /** Cloud over the whole catalogue tile, in percent, as the provider reports it. */
  tile_cloud_percent: number | null
  /** Share of the area itself the scene's SCL band calls cloud (0..1). */
  area_cloud_fraction: number | null
  /** Share of the area the scene has data for (0..1). */
  coverage: number
  resolution_m: number
  bands: string[]
}

export type AcquisitionStatus = 'fetched' | 'needs_location' | 'unavailable' | 'failed'

/** `app.schemas.acquisition.AcquisitionReport`. */
export interface AcquisitionReport {
  status: AcquisitionStatus
  message: string
  /** The place as resolved: the geocoder's full name, or the coordinates. */
  place: string | null
  place_source: string | null
  /** `[west, south, east, north]` in degrees - the area actually downloaded. */
  bbox_lonlat: number[] | null
  period: string | null
  provider: string
  attribution: string
  scenes: AcquiredScene[]
  notes: string[]
}

export interface TaskListEntry {
  task_id: string
  query: string
  status: TaskStatus
  outcome: string
  answer: string
}

export interface ValidationResponse {
  query: string
  status: TaskStatus
  task_category: string
  selected_tool: string | null
  /** True only when every check, including the registry policy, passed. */
  would_execute: boolean
  /** When `would_execute` is false: what stands in the way. */
  reason: string | null
  images: ImageSummary[]
  validation: ValidationReport
  explanation: Explanation
  route: Engine
  understood: Understanding
  trace: TraceEvent[]
}

export interface BackendInfo {
  raster_backend: string
  numpy_available: boolean
  supports_compressed_geotiff: boolean
}

export interface CapabilitiesResponse {
  version: string
  /** Tool ids that can actually execute right now. */
  executable: string[]
  tools: ToolSummary[]
  accepted_formats: string[]
  max_upload_bytes: number
  max_images_per_task: number
  agent_provider: string
  agent_llm_enabled: boolean
  /** `hosted` or `ollama` when the VLM core is on; null when it is off. */
  vlm_provider: string | null
  /** True when the vision model runs on this machine. */
  vlm_local: boolean
  /** True when a question may be asked without imagery: the server then
   *  fetches Sentinel-2 / Sentinel-1 scenes for the place it names. */
  auto_fetch: boolean
  backend: BackendInfo
}

export interface HealthResponse {
  status: string
  registered_tools: number
  implemented_tools: string[]
  backend: BackendInfo
}

/** `app.api.errors.ErrorResponse` - the single error envelope. */
export interface ErrorEnvelope {
  error: boolean
  code: string
  message: string
  detail: string
  fields: { field: string; message: string }[]
  incident_id: string | null
}
