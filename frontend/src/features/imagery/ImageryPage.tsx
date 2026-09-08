import { Link } from 'react-router-dom'
import { Checkbox, Notice, Panel, TextField } from '../../components/ui'
import { UploadDropzone } from '../query/UploadDropzone'
import { useWorkspace } from '../../context/workspaceContext'
import { useCapabilities } from '../../context/capabilitiesContext'
import { formatBytes } from '../../utils/format'

/**
 * Staging imagery.
 *
 * The backend has no dataset library and no standalone upload endpoint:
 * rasters are sent with the question, in one request. This screen is therefore
 * honest about what it is - a staging area for the next query - rather than
 * presenting itself as storage.
 */
export function ImageryPage() {
  const { files, asScene, setAsScene, sensor, setSensor } = useWorkspace()
  const { capabilities } = useCapabilities()
  const usable = files.filter((entry) => !entry.problem)

  return (
    <div className="sq-page">
      <header className="sq-page__head">
        <div>
          <h1 className="sq-page__title">Imagery</h1>
          <p className="sq-page__lede">
            Rasters staged for your next question. They are held in this browser
            and sent with the query, so nothing is stored on the service until
            you run an analysis.
          </p>
        </div>
        {usable.length > 0 ? (
          <Link to="/" className="sq-btn sq-btn--primary">
            Ask about this imagery
          </Link>
        ) : null}
      </header>

      <Panel title="Staged rasters">
        <UploadDropzone />
      </Panel>

      {files.length > 1 ? (
        <Panel title="How these files relate">
          <div className="sq-imagery-options">
            <Checkbox
              label="These files are bands of one scene"
              checked={asScene}
              onChange={(event) => setAsScene(event.target.checked)}
            />
            <p className="sq-page__lede">
              Satellite products usually ship one file per band. With this on,
              SatQuery treats the uploads as a single image and resamples the
              bands onto a common grid. With it off, each file is a separate
              image — which is what change detection needs.
            </p>
            {asScene ? (
              <div style={{ maxWidth: 300 }}>
                <TextField
                  label="Sensor (optional)"
                  placeholder="sentinel2"
                  value={sensor}
                  onChange={(event) => setSensor(event.target.value)}
                  hint="Lets SatQuery resolve numeric band names such as B04 and B08."
                  autoCapitalize="none"
                  spellCheck={false}
                />
              </div>
            ) : null}
          </div>
        </Panel>
      ) : null}

      <Notice tone="info" title="What this service accepts">
        {capabilities ? (
          <>
            {capabilities.accepted_formats.join(', ')} rasters, up to{' '}
            {capabilities.max_images_per_task} per analysis and{' '}
            {formatBytes(capabilities.max_upload_bytes)} each.{' '}
            {capabilities.backend.supports_compressed_geotiff
              ? 'Compressed and tiled GeoTIFF are readable on this deployment.'
              : 'This deployment reads uncompressed baseline GeoTIFF only, because GDAL is not installed.'}
          </>
        ) : (
          'Connecting to the analysis service to read its limits.'
        )}
      </Notice>
    </div>
  )
}
