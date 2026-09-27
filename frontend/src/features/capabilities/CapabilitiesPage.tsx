import { useMemo, useState } from 'react'
import {
  Definition,
  Definitions,
  Disclosure,
  Segmented,
  Skeleton,
  StateBlock,
  Tag,
} from '../../components/ui'
import { AlertIcon } from '../../components/icons'
import { useCapabilities } from '../../context/capabilitiesContext'
import { ENGINE_META, TOOL_TYPE_LABELS, OUTPUT_TYPE_LABELS, bandLabel } from '../../utils/labels'
import type { ToolSummary, ToolType } from '../../types/api'
import './capabilities.css'

type Filter = 'available' | 'all'

/**
 * The capability registry, as the service reports it.
 *
 * Generated from `/api/capabilities`, which the backend builds from the tool
 * registry on every call. That is the point of the endpoint: a tool that is
 * registered but has no implementation bound appears here marked as such,
 * rather than being quietly listed as available. This screen inherits that
 * honesty instead of curating a marketing list.
 */
export function CapabilitiesPage() {
  const { capabilities, loading, error, reload } = useCapabilities()
  const [filter, setFilter] = useState<Filter>('available')

  const grouped = useMemo(() => {
    const tools = capabilities?.tools ?? []
    const visible =
      filter === 'available' ? tools.filter((tool) => tool.implemented) : tools

    const groups = new Map<ToolType, ToolSummary[]>()
    for (const tool of visible) {
      const bucket = groups.get(tool.tool_type) ?? []
      bucket.push(tool)
      groups.set(tool.tool_type, bucket)
    }
    return [...groups.entries()]
  }, [capabilities, filter])

  if (loading) {
    return (
      <div className="sq-page">
        <Skeleton height={30} width="30%" />
        {[0, 1, 2].map((index) => (
          <Skeleton key={index} height={120} radius={12} />
        ))}
      </div>
    )
  }

  if (error || !capabilities) {
    return (
      <div className="sq-page">
        <StateBlock
          icon={<AlertIcon size={20} />}
          tone="danger"
          title="Capabilities could not be read"
          body={error ?? 'The analysis service did not answer.'}
          actions={
            <button type="button" className="sq-btn sq-btn--primary" onClick={reload}>
              Retry
            </button>
          }
        />
      </div>
    )
  }

  const registered = capabilities.tools.length
  const executable = capabilities.executable.length

  return (
    <div className="sq-page">
      <header className="sq-page__head">
        <div>
          <h1 className="sq-page__title">Capabilities</h1>
          <p className="sq-page__lede">
            Everything this deployment is allowed to run. {executable} of{' '}
            {registered} registered capabilities can run here right now;
            nothing outside this list can execute.
          </p>
          <p className="sq-page__lede">
            {!capabilities.vlm_provider
              ? 'The vision-language model core is off; every answer comes from the deterministic engines.'
              : capabilities.vlm_local
                ? 'The vision-language model core is on and runs on this machine; no imagery leaves it.'
                : 'The vision-language model core is on and uses a hosted model: rendered previews of your imagery are sent to it.'}
          </p>
        </div>
        <Segmented
          label="Capability filter"
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'available', label: `Available (${executable})` },
            { value: 'all', label: `All (${registered})` },
          ]}
        />
      </header>

      {grouped.map(([type, tools]) => (
        <section className="sq-capgroup" key={type}>
          <h2 className="sq-label">{TOOL_TYPE_LABELS[type] ?? type}</h2>
          <div className="sq-capgroup__grid">
            {tools.map((tool) => (
              <CapabilityCard key={tool.tool_id} tool={tool} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

/** A tool that is built but that an operator has not switched on. */
function isSwitchedOff(tool: ToolSummary): boolean {
  return !tool.implemented && tool.bound
}

function CapabilityCard({ tool }: { tool: ToolSummary }) {
  const parameters = Object.entries(tool.parameters)

  return (
    <article
      className={`sq-cap${tool.implemented ? '' : ' sq-cap--unbound'}`}
      aria-label={tool.name}
    >
      <header className="sq-cap__head">
        <h3 className="sq-cap__name">{tool.name}</h3>
        {ENGINE_META[tool.engine] ? (
          <Tag tone={ENGINE_META[tool.engine].tone} title={ENGINE_META[tool.engine].description}>
            {ENGINE_META[tool.engine].label}
          </Tag>
        ) : null}
        {tool.implemented ? (
          <Tag tone="success">Available</Tag>
        ) : (
          <Tag tone="neutral" title={tool.availability_note ?? undefined}>
            {isSwitchedOff(tool) ? 'Switched off' : 'Not built yet'}
          </Tag>
        )}
      </header>

      <p className="sq-cap__description">{tool.description}</p>

      {!tool.implemented && tool.availability_note ? (
        <p className="sq-cap__param-note">{tool.availability_note}</p>
      ) : null}

      <dl className="sq-cap__facts">
        <div>
          <dt>Input</dt>
          <dd>
            {tool.min_images === tool.max_images
              ? `${tool.min_images} image${tool.min_images > 1 ? 's' : ''}`
              : `${tool.min_images}–${tool.max_images} images`}
            {tool.requires_temporal_pair ? ', two dates' : ''}
          </dd>
        </div>
        <div>
          <dt>Modality</dt>
          <dd>
            {tool.supported_modalities.length > 0
              ? tool.supported_modalities.join(', ')
              : 'any'}
          </dd>
        </div>
        <div>
          <dt>Output</dt>
          <dd>{OUTPUT_TYPE_LABELS[tool.output_type] ?? tool.output_type}</dd>
        </div>
      </dl>

      {tool.required_bands.length > 0 ? (
        <div className="sq-cap__bands">
          <span className="sq-label">Bands required</span>
          <div className="sq-cap__band-list">
            {tool.required_bands.map((band) => (
              <Tag key={band} tone="accent">
                {bandLabel(band)}
              </Tag>
            ))}
          </div>
        </div>
      ) : null}

      {parameters.length > 0 ? (
        <Disclosure summary={`Parameters (${parameters.length})`}>
          <Definitions>
            {parameters.map(([name, type]) => (
              <Definition term={name} key={name}>
                <span className="sq-mono">{type}</span>
              </Definition>
            ))}
          </Definitions>
          <p className="sq-cap__param-note">
            SatQuery resolves these from your question. They are listed for
            reference, not as controls to set by hand.
          </p>
        </Disclosure>
      ) : null}

      <footer className="sq-cap__foot sq-mono">
        {tool.tool_id} · v{tool.version}
      </footer>
    </article>
  )
}
