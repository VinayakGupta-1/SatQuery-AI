import { Disclosure, Definition, Definitions, Tag } from '../../../components/ui'
import { GlobeIcon } from '../../../components/icons'
import { bandLabel } from '../../../utils/labels'
import {
  formatDate,
  formatDimensions,
  formatIndex,
  formatResolution,
} from '../../../utils/format'
import type { ImageSummary } from '../../../types/api'

/**
 * What the server determined about the imagery it was given.
 *
 * Every field here was read from the file, not from the client - the backend
 * opens each upload and describes it - so this is the ground truth of what was
 * analysed. It is folded away by default: a user who asked about vegetation
 * does not need the geotransform, but an analyst checking a result does.
 */
export function ImageryPanel({ images }: { images: ImageSummary[] }) {
  if (images.length === 0) return null

  return (
    <Disclosure
      icon={<GlobeIcon size={15} />}
      summary={`Imagery analysed (${images.length})`}
    >
      <div className="sq-imagery">
        {images.map((image) => {
          const georeferenced = image.bounds !== null && image.crs !== null
          return (
            <article className="sq-imagery__card" key={image.id}>
              <header className="sq-imagery__head">
                <h4 className="sq-imagery__name">{image.filename}</h4>
                <div className="sq-imagery__tags">
                  {image.modality ? (
                    <Tag tone="info">{image.modality}</Tag>
                  ) : null}
                  {image.sensor ? <Tag>{image.sensor}</Tag> : null}
                  {georeferenced ? (
                    <Tag tone="success">Georeferenced</Tag>
                  ) : (
                    <Tag tone="warning">No CRS</Tag>
                  )}
                </div>
              </header>

              <Definitions>
                <Definition term="Size">
                  {formatDimensions(image.width, image.height)}
                  {image.band_count ? ` · ${image.band_count} bands` : ''}
                </Definition>

                {image.bands.length > 0 ? (
                  <Definition term="Bands">
                    {image.bands.map(bandLabel).join(', ')}
                  </Definition>
                ) : null}

                {image.acquisition_date ? (
                  <Definition term="Acquired">
                    {formatDate(image.acquisition_date)}
                  </Definition>
                ) : null}

                {image.crs ? <Definition term="CRS">{image.crs}</Definition> : null}

                {image.resolution ? (
                  <Definition term="Ground sample">
                    {formatResolution(image.resolution, image.crs)}
                  </Definition>
                ) : null}

                {image.bounds ? (
                  <Definition term="Extent">
                    <span className="sq-mono sq-imagery__bounds">
                      {image.bounds.map((value) => formatIndex(value, 2)).join(', ')}
                    </span>
                    <span className="sq-imagery__bounds-note">
                      min x, min y, max x, max y in CRS units
                    </span>
                  </Definition>
                ) : null}

                {image.dtype ? <Definition term="Type">{image.dtype}</Definition> : null}
              </Definitions>
            </article>
          )
        })}
      </div>
    </Disclosure>
  )
}
