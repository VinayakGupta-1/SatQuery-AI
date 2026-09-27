import { Panel, Tag } from '../../../components/ui'
import { humanise } from '../../../utils/labels'
import type { Finding, FindingLocation } from '../../../types/api'

function placeTag(location: FindingLocation | null): string | null {
  if (!location) return null
  if (location.widespread) return 'Scene-wide'
  if (location.sector) return humanise(location.sector)
  if (location.box_fraction) return 'Outlined'
  return null
}

/**
 * The answer broken into checkable parts: what, how much, and where.
 *
 * Every finding is derived from numbers the tool reported, and its detail
 * already says where it lies in words and coordinates. The tag repeats the
 * compass sector so a reader can scan for "what is in the north-west" without
 * reading every line.
 */
export function Findings({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) return null

  return (
    <Panel title="Findings">
      <ol className="sq-findings">
        {findings.map((finding, index) => {
          const place = placeTag(finding.location)
          return (
            <li className="sq-findings__item" key={`${finding.title}-${index}`}>
              <div className="sq-findings__head">
                <span className="sq-findings__title">{finding.title}</span>
                {place ? <Tag>{place}</Tag> : null}
              </div>
              {finding.detail ? <p className="sq-findings__detail">{finding.detail}</p> : null}
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}
