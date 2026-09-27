import { humanise, modalityLabel, taskLabel } from '../../../utils/labels'
import type { Understanding } from '../../../types/api'

/**
 * What the question was read as, before anything ran.
 *
 * Intent, place, period, measure and sensor are the parts of the sentence the
 * understanding layer pulled out. They are shown on every result, refusals
 * included, because a wrong answer usually starts with a misread question and
 * this is where a reader can see that it happened. Only what was actually
 * found is listed: an empty slot says nothing, so it is not drawn.
 */
export function UnderstandingStrip({ understood }: { understood: Understanding }) {
  const items: { term: string; value: string }[] = []
  if (understood.intent) items.push({ term: 'Intent', value: taskLabel(understood.intent) })
  if (understood.locations.length > 0) {
    items.push({ term: 'Place', value: understood.locations.join(', ') })
  }
  if (understood.area) items.push({ term: 'Area', value: understood.area })
  if (understood.period) items.push({ term: 'Period', value: understood.period })
  if (understood.metrics.length > 0) {
    items.push({ term: 'Measure', value: understood.metrics.map(humanise).join(', ') })
  }
  // What the imagery is outranks what the sentence said about it.
  const modality = understood.imagery_modality ?? understood.query_modality
  if (modality) items.push({ term: 'Imagery', value: modalityLabel(modality) })

  if (items.length === 0) return null

  return (
    <dl className="sq-understood" aria-label="How the question was read">
      <span className="sq-understood__lead sq-label">Read as</span>
      {items.map((item) => (
        <div className="sq-understood__item" key={item.term}>
          <dt>{item.term}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
