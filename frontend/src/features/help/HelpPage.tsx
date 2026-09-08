import { Link } from 'react-router-dom'
import { Panel } from '../../components/ui'
import { useCapabilities } from '../../context/capabilitiesContext'
import './help.css'

/**
 * How to get a useful answer.
 *
 * Written against what this deployment actually does, not against a generic
 * idea of a satellite platform: the accepted formats and the executable
 * capability list are read from the service rather than hard-coded.
 */
export function HelpPage() {
  const { capabilities, executableTools } = useCapabilities()

  return (
    <div className="sq-page">
      <header className="sq-page__head">
        <div>
          <h1 className="sq-page__title">Help</h1>
          <p className="sq-page__lede">
            SatQuery reads your question, decides which analysis answers it,
            checks your imagery can support that analysis, and runs it. You do
            not choose a tool — you ask a question.
          </p>
        </div>
      </header>

      <Panel title="Asking a good question">
        <div className="sq-help">
          <p>
            Say what you want to know about the ground, not which algorithm to
            run. SatQuery maps the question to a capability itself, and shows
            you which one it chose under <strong>Analysis details</strong> on
            every result.
          </p>
          <ul className="sq-help__examples">
            <li>
              <span className="sq-help__good">“How healthy is the vegetation here?”</span>
              <span className="sq-help__note">
                → a vegetation index over one scene
              </span>
            </li>
            <li>
              <span className="sq-help__good">“Where is the surface water?”</span>
              <span className="sq-help__note">→ a water index over one scene</span>
            </li>
            <li>
              <span className="sq-help__good">
                “What changed between these two dates?”
              </span>
              <span className="sq-help__note">
                → a bi-temporal comparison, needs two images
              </span>
            </li>
          </ul>
          <p>
            If the question cannot be matched, SatQuery says so and lists what it
            can do instead — it never guesses at an analysis you did not ask for.
          </p>
        </div>
      </Panel>

      <Panel title="Where to get imagery">
        <div className="sq-help">
          <p>
            SatQuery analyses <strong>satellite rasters</strong>, not pictures.
            A JPEG or PNG photograph carries no spectral bands and no
            georeferencing, so there is nothing to compute an index from — those
            files are refused rather than analysed badly.
          </p>

          <h3 className="sq-help__subhead">Free sources</h3>
          <ul className="sq-help__sources">
            <li>
              <strong>Copernicus Browser</strong>
              <span>
                Sentinel-2, 10 m, free. Search a location, pick a low-cloud
                date, download the bands as GeoTIFF.
              </span>
              <span className="sq-mono">browser.dataspace.copernicus.eu</span>
            </li>
            <li>
              <strong>USGS EarthExplorer</strong>
              <span>
                Landsat 8/9, 30 m, free. Full archive back to the 1970s, good
                for change over long periods.
              </span>
              <span className="sq-mono">earthexplorer.usgs.gov</span>
            </li>
            <li>
              <strong>Bhoonidhi (ISRO)</strong>
              <span>
                Resourcesat and Cartosat products over India, free after
                registration.
              </span>
              <span className="sq-mono">bhoonidhi.nrsc.gov.in</span>
            </li>
          </ul>

          <h3 className="sq-help__subhead">Nothing to hand?</h3>
          <p>
            The repository ships a generator for a co-registered pair of
            synthetic Sentinel-2-style scenes, so the whole system can be tried
            without downloading anything:
          </p>
          <pre className="sq-help__code">
            python backend/scripts/make_demo_rasters.py demo_data
          </pre>
          <p>
            They are synthetic but they are real GeoTIFFs — georeferenced,
            four-band, band-named — so everything computed from them is a
            genuine computation.
          </p>
        </div>
      </Panel>

      <Panel title="What to upload">
        <div className="sq-help">
          <p>
            {capabilities
              ? `Rasters in ${capabilities.accepted_formats.join(', ')} format, up to ${
                  capabilities.max_images_per_task
                } per analysis.`
              : 'GeoTIFF and JPEG 2000 rasters.'}{' '}
            The service opens every file and reads its own metadata, so band
            names, sensor and acquisition date come from the raster rather than
            from anything you type.
          </p>

          <h3 className="sq-help__subhead">One file per band</h3>
          <p>
            Satellite products usually ship each band as a separate file. When
            you upload B04 and B08 of the same scene, tick{' '}
            <strong>“These files are bands of one scene”</strong> — otherwise
            SatQuery treats them as two separate images. Naming the sensor
            (<span className="sq-mono">sentinel2</span>) lets it resolve numeric
            band names.
          </p>

          <h3 className="sq-help__subhead">Comparing two dates</h3>
          <p>
            Change detection needs a co-registered pair: the same pixel grid,
            the same CRS, two different acquisition dates. If the pair is not
            aligned, SatQuery refuses rather than silently reprojecting — a
            misaligned comparison produces a confident and completely wrong
            answer.
          </p>

          <h3 className="sq-help__subhead">Cloud and nodata</h3>
          <p>
            Pixels that cannot be computed are left as nodata and excluded from
            every statistic, so a cloudy scene reports a smaller observed area
            rather than a contaminated average.
          </p>
        </div>
      </Panel>

      <Panel title="What this deployment can run">
        <div className="sq-help">
          {executableTools.length === 0 ? (
            <p>
              No capability currently has an implementation bound. Check the{' '}
              <Link to="/capabilities">capabilities page</Link> for the full
              registry.
            </p>
          ) : (
            <ul className="sq-help__capabilities">
              {executableTools.map((tool) => (
                <li key={tool.tool_id}>
                  <strong>{tool.name}</strong>
                  <span>{tool.description}</span>
                </li>
              ))}
            </ul>
          )}
          <p>
            <Link to="/capabilities">See every registered capability</Link>,
            including those declared but not yet built.
          </p>
        </div>
      </Panel>

      <Panel title="Where your imagery goes">
        <div className="sq-help">
          <p>
            Files stay in this browser until you run an analysis. Running one
            sends them to the SatQuery backend, which stores them under a
            server-generated name for the duration of the task and returns the
            result. Nothing is sent anywhere else.
          </p>
          <p>
            Results are kept in the service's memory and are lost when it
            restarts. Download anything you need to keep from{' '}
            <Link to="/exports">Exports</Link>.
          </p>
        </div>
      </Panel>
    </div>
  )
}
