import { Panel } from '../../../components/ui'
import { RasterViewer } from '../../raster/RasterViewer'
import { ClassBreakdown } from '../parts/ClassBreakdown'
import { PreviewPair, type PreviewItem } from '../parts/PreviewPair'
import { artifactUrl } from '../../../services/satquery'
import { formatDate, formatLonLat } from '../../../utils/format'
import { CHANGE_CODES, CHANGE_ORDER } from '../../../utils/labels'
import type { ArtifactLink, CaptionRegion, TaskResponse } from '../../../types/api'

/** Outline colours for grounded regions, distinct on the dark ground. */
const REGION_COLOURS = ['#8fd0e2', '#c9a45c', '#56b98d', '#d97a6d', '#b39ddb', '#e6c86e', '#7aa7d6', '#f0a0c0']

function modelLine(model: string | undefined) {
  return model ? (
    <>
      Answered by <span className="sq-mono">{model}</span>.
    </>
  ) : null
}

/**
 * An answer written by the vision-language model core.
 *
 * The answer itself is already shown above, with its caveat. What this adds
 * is what the model was shown and what it pointed at, because an answer is
 * only as good as the picture it was read from and the reader is entitled to
 * check it:
 *
 * - a caption, with the regions it names outlined on the picture;
 * - a change question, with both dates and the measured change map the
 *   model was given as fact;
 * - an optical + radar question, with both pictures;
 * - any other question, with the one picture.
 */
export function TextResult({ result }: { result: TaskResponse }) {
  switch (result.tool) {
    case 'image_captioning':
      return <CaptionView result={result} />
    case 'change_vqa':
      return <ChangeQuestionView result={result} />
    default:
      return <QuestionView result={result} />
  }
}

function QuestionView({ result }: { result: TaskResponse }) {
  const { data, artifacts } = result
  if (data.cross_modal) {
    const optical = artifacts.find((a) => a.artifact_id === 'vqa_preview_optical')
    const radar = artifacts.find((a) => a.artifact_id === 'vqa_preview_sar')
    const items: PreviewItem[] = []
    if (optical) items.push({ artifact: optical, label: 'Optical' })
    if (radar) items.push({ artifact: radar, label: 'Radar (SAR)' })
    return (
      <Panel title="What the model was shown">
        <PreviewPair
          items={items}
          caption={`Read together: cloud hides the ground from the optical picture but not from radar. ${
            data.model ? `Answered by ${data.model}.` : ''
          }`}
        />
      </Panel>
    )
  }

  const preview = artifacts.find((artifact) => artifact.kind === 'image')
  if (!preview) return null
  return (
    <Panel title="What the model was shown">
      <figure className="sq-vqa">
        <img
          className="sq-vqa__image"
          src={artifactUrl(preview)}
          alt={data.rendering_description ?? 'The rendered preview the model answered from'}
        />
        <figcaption className="sq-vqa__caption">
          {data.rendering_description ? `${data.rendering_description}. ` : ''}
          {modelLine(data.model)}
        </figcaption>
      </figure>
    </Panel>
  )
}

/**
 * A caption with its regions outlined.
 *
 * Boxes are placed by the fractions the model gave, so they sit on the
 * picture it saw at any display size. They are the model's proposals, not
 * measured boundaries, and the legend says so.
 */
function CaptionView({ result }: { result: TaskResponse }) {
  const { data, artifacts } = result
  const preview = artifacts.find((artifact) => artifact.artifact_id === 'caption_preview')
  const regions: CaptionRegion[] = data.regions ?? []
  if (!preview) return null

  return (
    <Panel title="Regions the description refers to">
      <figure className="sq-vqa">
        <div className="sq-regions">
          <img
            className="sq-vqa__image sq-regions__image"
            src={artifactUrl(preview)}
            alt={data.rendering_description ?? 'The rendered preview the model described'}
          />
          {regions.map((region, index) => {
            const [x0, y0, x1, y1] = region.box_fraction
            return (
              <span
                key={`${region.label}-${index}`}
                className="sq-regions__box"
                style={{
                  left: `${x0 * 100}%`,
                  top: `${y0 * 100}%`,
                  width: `${(x1 - x0) * 100}%`,
                  height: `${(y1 - y0) * 100}%`,
                  borderColor: REGION_COLOURS[index % REGION_COLOURS.length],
                }}
                aria-hidden="true"
              >
                <span
                  className="sq-regions__tag"
                  style={{ background: REGION_COLOURS[index % REGION_COLOURS.length] }}
                >
                  {index + 1}
                </span>
              </span>
            )
          })}
        </div>

        {regions.length > 0 ? (
          <ol className="sq-regions__legend">
            {regions.map((region, index) => (
              <li key={`${region.label}-${index}`}>
                <span
                  className="sq-regions__swatch"
                  style={{ background: REGION_COLOURS[index % REGION_COLOURS.length] }}
                  aria-hidden="true"
                >
                  {index + 1}
                </span>
                <span className="sq-regions__label">{region.label}</span>
                {region.centre_lonlat ? (
                  <span className="sq-regions__coords sq-mono">{formatLonLat(region.centre_lonlat)}</span>
                ) : null}
              </li>
            ))}
          </ol>
        ) : null}

        <figcaption className="sq-vqa__caption">
          {regions.length > 0
            ? 'Outlines are the model’s proposals, placed back on the map, not measured boundaries. '
            : 'The model outlined no regions. '}
          {(data.notes ?? []).join(' ')} {modelLine(data.model)}
        </figcaption>
      </figure>
    </Panel>
  )
}

/**
 * A question about change: both dates, then the measured change the model
 * was told to treat as fact, so its description can be checked against it.
 */
function ChangeQuestionView({ result }: { result: TaskResponse }) {
  const { data, artifacts } = result
  const measured = data.measured ?? {}
  const earlierDate = typeof measured.earlier_date === 'string' ? measured.earlier_date : null
  const laterDate = typeof measured.later_date === 'string' ? measured.later_date : null
  const crs = result.images[0]?.crs ?? null

  const find = (id: string): ArtifactLink | undefined =>
    artifacts.find((artifact) => artifact.artifact_id === id)
  const items: PreviewItem[] = []
  const earlier = find('earlier_preview')
  const later = find('later_preview')
  if (earlier) items.push({ artifact: earlier, label: earlierDate ? `Earlier · ${formatDate(earlierDate)}` : 'Earlier' })
  if (later) items.push({ artifact: later, label: laterDate ? `Later · ${formatDate(laterDate)}` : 'Later' })
  const changeMap = find('change_class_raster')

  return (
    <>
      {items.length > 0 ? (
        <Panel title="What the model was shown">
          <PreviewPair
            items={items}
            caption={`Both dates on one brightness stretch, so a difference in the picture is a difference on the ground. ${
              data.model ? `Answered by ${data.model}.` : ''
            }`}
          />
        </Panel>
      ) : null}

      {changeMap ? (
        <Panel bare>
          <div className="sq-result__viewer">
            <RasterViewer
              url={artifactUrl(changeMap)}
              artifactId={changeMap.artifact_id}
              valueLabel="class"
              caption="Measured change: the figures the model was given and told not to contradict."
              classCodes={CHANGE_CODES}
            />
          </div>
        </Panel>
      ) : null}

      {data.classes ? (
        <Panel title="Measured change">
          <ClassBreakdown
            classes={data.classes}
            crs={crs}
            order={CHANGE_ORDER}
            caption={
              typeof measured.formula === 'string'
                ? `Classified from ${measured.formula}${
                    typeof measured.threshold_description === 'string'
                      ? `, with a ${measured.threshold_description}`
                      : ''
                  }.`
                : undefined
            }
          />
        </Panel>
      ) : null}
    </>
  )
}
