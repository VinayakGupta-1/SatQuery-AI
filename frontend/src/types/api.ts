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
  /** False when the tool is registered but has no implementation bound. */
  implemented: boolean
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
 * The tool-specific `data` block. The keys present depend on which tool ran;
 * `classes` is normalised onto every response by the API layer.
 */
export interface ResultData {
  classes?: Record<string, ClassSummary>
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
  confidence: number | null
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
  would_execute: boolean
  images: ImageSummary[]
  validation: ValidationReport
  explanation: Explanation
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
