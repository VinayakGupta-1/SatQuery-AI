import { Panel } from '../../components/ui'
import { ResultHeader } from './parts/ResultHeader'
import { AnalysisDetails } from './parts/AnalysisDetails'
import { ImageryPanel } from './parts/ImageryPanel'
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
