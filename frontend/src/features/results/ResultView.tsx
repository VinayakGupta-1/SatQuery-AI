import { Panel } from '../../components/ui'
import { ResultHeader } from './parts/ResultHeader'
import { AnalysisDetails } from './parts/AnalysisDetails'
import { ImageryPanel } from './parts/ImageryPanel'
import { ArtifactList } from './parts/ArtifactList'
import { IndexResult } from './variants/IndexResult'
import { ChangeResult } from './variants/ChangeResult'
import { ClassesResult } from './variants/ClassesResult'
import { DetectionsResult } from './variants/DetectionsResult'
import { GenericResult } from './variants/GenericResult'
import { NonSuccessResult } from './variants/NonSuccessResult'
import { formatPercent } from '../../utils/format'
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
      // The answer above is the whole result for a text capability; there is
      // nothing further to draw.
      return null
    case 'mask':
    default:
      return <GenericResult result={result} />
  }
}

interface ResultViewProps {
  result: TaskResponse
  durationMs?: number | null
}

export function ResultView({ result, durationMs }: ResultViewProps) {
  const successful = result.status === 'success'

  return (
    <article className="sq-result">
      <ResultHeader result={result} durationMs={durationMs} />

      {successful ? (
        <div className="sq-result__answer">
          <p>{result.answer}</p>
          {result.confidence != null ? (
            <span className="sq-result__confidence" title="Reported by the capability">
              Confidence {formatPercent(result.confidence, 0)}
            </span>
          ) : null}
        </div>
      ) : null}

      <Presentation result={result} />

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
