import { Suspense, lazy, useMemo } from 'react'
import { Panel } from '../../components/ui'
import { ResultHeader } from './parts/ResultHeader'
import { AnalysisDetails } from './parts/AnalysisDetails'
import { ImageryPanel } from './parts/ImageryPanel'
import { AcquisitionPanel } from './parts/AcquisitionPanel'
import { ArtifactList } from './parts/ArtifactList'
import { UnderstandingStrip } from './parts/UnderstandingStrip'
import { Findings } from './parts/Findings'
import { ConfidencePanel } from './parts/ConfidencePanel'
import { IndexResult } from './variants/IndexResult'
import { ChangeResult } from './variants/ChangeResult'
import { ClassesResult } from './variants/ClassesResult'
import { DetectionsResult } from './variants/DetectionsResult'
import { GenericResult } from './variants/GenericResult'
import { TextResult } from './variants/TextResult'
import { NonSuccessResult } from './variants/NonSuccessResult'
import { formatPercent } from '../../utils/format'
import { CONFIDENCE_META } from '../../utils/labels'
import type { TaskResponse } from '../../types/api'
import './results.css'

const AreaMap = lazy(() => import('../map/AreaMap').then((module) => ({ default: module.AreaMap })))

/** The area a result describes: what was fetched, else what was uploaded. */
function areaOf(result: TaskResponse): number[] | null {
  if (result.acquisition?.bbox_lonlat) return result.acquisition.bbox_lonlat
  const boxes = result.images.map((image) => image.bounds_lonlat).filter(Boolean) as number[][]
  if (boxes.length === 0) return null
  return [
    Math.min(...boxes.map((box) => box[0])),
    Math.min(...boxes.map((box) => box[1])),
    Math.max(...boxes.map((box) => box[2])),
    Math.max(...boxes.map((box) => box[3])),
  ]
}

/**
 * Choose how to present a result.
 *
 * Status first: a run that produced no analysis is a different screen, not a
 * blank version of the same one. Then `output_type`, which the registry
 * defines precisely so a frontend can switch on it.
 */
function Presentation({ result }: { result: TaskResponse }) {
  if (result.status !== 'success') return <NonSuccessResult result={result} />

  switch (result.output_type) {
    case 'raster_index':
      return <IndexResult result={result} />
    case 'change_map':
      return <ChangeResult result={result} />
    case 'classes':
      return <ClassesResult result={result} />
    case 'detections':
      return <DetectionsResult result={result} />
    case 'text':
      // The answer above is the result; what remains is the picture it was
      // read from.
      return <TextResult result={result} />
    case 'mask':
    default:
      return <GenericResult result={result} />
  }
}

interface ResultViewProps {
  result: TaskResponse
  durationMs?: number | null
}

/**
 * One result, laid out the way the answer is built: the question as it was
 * read, the grounded answer, the map, the findings and how far to trust them,
 * and then - folded away - the imagery and the full audit trail.
 */
export function ResultView({ result, durationMs }: ResultViewProps) {
  const successful = result.status === 'success'
  const report = result.confidence_report
  const grounded = successful && (result.findings.length > 0 || report != null)
  // Stable between renders, so the map frames the area once.
  const area = useMemo(() => areaOf(result), [result])

  return (
    <article className="sq-result">
      <ResultHeader result={result} durationMs={durationMs} />

      <UnderstandingStrip understood={result.understood} />

      {successful ? (
        <div className="sq-result__answer">
          <p>{result.answer}</p>
          {report ? (
            <span className="sq-result__confidence" title={report.basis}>
              {CONFIDENCE_META[report.level].label}
              {report.score != null ? ` · ${formatPercent(report.score, 0)}` : ''}
            </span>
          ) : null}
        </div>
      ) : null}

      <Presentation result={result} />

      {result.acquisition ? <AcquisitionPanel report={result.acquisition} /> : null}

      {area ? (
        <Panel title="Where this is">
          <Suspense fallback={<div className="sq-boot" aria-busy="true" />}>
            <AreaMap
              box={area}
              label="Map outlining the area this result describes"
              height={300}
            />
          </Suspense>
        </Panel>
      ) : null}

      {grounded ? (
        <div className="sq-result__grounding">
          <Findings findings={result.findings} />
          {report ? <ConfidencePanel report={report} /> : null}
        </div>
      ) : null}

      {successful && result.artifacts.length > 0 ? (
        <Panel title="Downloads">
          <ArtifactList artifacts={result.artifacts} />
        </Panel>
      ) : null}

      <div className="sq-result__advanced">
        <ImageryPanel images={result.images} />
        <AnalysisDetails result={result} durationMs={durationMs} />
      </div>
    </article>
  )
}
