import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { buildLookup, rampFor, rampGradient, type Ramp } from './colormaps'
import { useGeoTiff } from './useGeoTiff'
import { IconButton, Skeleton, StateBlock } from '../../components/ui'
import { AlertIcon, ResetIcon, ZoomInIcon, ZoomOutIcon } from '../../components/icons'
import { formatIndex } from '../../utils/format'
import './raster.css'

interface RasterViewerProps {
  /** Absolute URL of the artifact to draw. */
  url: string
  /** Artifact id, used to pick the ramp for change rasters. */
  artifactId: string
  /** `data.index` from the result, e.g. `NDVI`. */
  indexName?: string | null
  /** Shown beneath the frame. */
  caption?: string
  /** Units for the value readout, when the raster is not an index. */
  valueLabel?: string
}

const MIN_ZOOM = 1
const MAX_ZOOM = 12

/**
 * The result raster, drawn and explorable.
 *
 * This is the geospatial view. It appears when - and only when - the analysis
 * actually produced a raster, which is why there is no permanent map anywhere
 * in this product: a question answered in prose does not get a map it does not
 * need.
 *
 * Pan and zoom are applied as a CSS transform over a canvas painted once at
 * decode resolution, so exploring the image costs no repaints and no decodes.
 */
export function RasterViewer({
  url,
  artifactId,
  indexName,
  caption,
  valueLabel,
}: RasterViewerProps) {
  const { raster, loading, error } = useGeoTiff(url)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const frameRef = useRef<HTMLDivElement | null>(null)

  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [probe, setProbe] = useState<{ x: number; y: number; value: number } | null>(null)
  const dragRef = useRef<{ x: number; y: number; id: number } | null>(null)

  const ramp: Ramp = useMemo(
    () => rampFor(indexName, artifactId),
    [indexName, artifactId],
  )

  /**
   * The value range the ramp is stretched across.
   *
   * Symmetric about the ramp's centre so that zero stays at the middle of a
   * diverging ramp - otherwise a scene that happens to be mostly vegetated
   * would render its bare soil as if it were water.
   */
  const domain = useMemo(() => {
    if (!raster) return { low: -1, high: 1 }
    const reach = Math.max(
      Math.abs(raster.min - ramp.centre),
      Math.abs(raster.max - ramp.centre),
    )
    const span = reach > 0 ? reach : 1
    return { low: ramp.centre - span, high: ramp.centre + span }
  }, [raster, ramp])

  // Paint once per decode: the transform handles everything after that.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !raster) return

    canvas.width = raster.width
    canvas.height = raster.height
    const context = canvas.getContext('2d')
    if (!context) return

    const lookup = buildLookup(ramp)
    const image = context.createImageData(raster.width, raster.height)
    const span = domain.high - domain.low || 1

    for (let index = 0; index < raster.values.length; index += 1) {
      const value = raster.values[index]
      const target = index * 4

      const missing =
        !Number.isFinite(value) ||
        (raster.nodata !== null &&
          (Number.isNaN(raster.nodata) ? Number.isNaN(value) : value === raster.nodata))

      if (missing) {
        // Nodata is transparent, not black: the panel beneath shows through so
        // a gap reads as "not observed" rather than as "zero".
        image.data[target + 3] = 0
        continue
      }

      const normalised = Math.min(1, Math.max(0, (value - domain.low) / span))
      const slot = Math.round(normalised * 255) * 3
      image.data[target] = lookup[slot]
      image.data[target + 1] = lookup[slot + 1]
      image.data[target + 2] = lookup[slot + 2]
      image.data[target + 3] = 255
    }

    context.putImageData(image, 0, 0)
  }, [raster, ramp, domain])

  const reset = useCallback(() => {
    setZoom(1)
    setOffset({ x: 0, y: 0 })
  }, [])

  /** Clamp the pan so the raster cannot be dragged off the frame. */
  const clampOffset = useCallback((next: { x: number; y: number }, scale: number) => {
    const frame = frameRef.current
    if (!frame) return next
    const limitX = (frame.clientWidth * (scale - 1)) / 2
    const limitY = (frame.clientHeight * (scale - 1)) / 2
    return {
      x: Math.min(limitX, Math.max(-limitX, next.x)),
      y: Math.min(limitY, Math.max(-limitY, next.y)),
    }
  }, [])

  const zoomBy = useCallback(
    (factor: number) => {
      setZoom((current) => {
        const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * factor))
        setOffset((position) =>
          next === MIN_ZOOM ? { x: 0, y: 0 } : clampOffset(position, next),
        )
        return next
      })
    },
    [clampOffset],
  )

  const readProbe = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const canvas = canvasRef.current
      if (!canvas || !raster) return

      const rect = canvas.getBoundingClientRect()
      const x = Math.floor(((event.clientX - rect.left) / rect.width) * raster.width)
      const y = Math.floor(((event.clientY - rect.top) / rect.height) * raster.height)
      if (x < 0 || y < 0 || x >= raster.width || y >= raster.height) {
        setProbe(null)
        return
      }

      const value = raster.values[y * raster.width + x]
      const missing =
        !Number.isFinite(value) ||
        (raster.nodata !== null &&
          (Number.isNaN(raster.nodata) ? Number.isNaN(value) : value === raster.nodata))
      setProbe(missing ? null : { x, y, value })
    },
    [raster],
  )

  /**
   * Wheel zoom, attached natively.
   *
   * React registers `onWheel` passively, so `preventDefault` inside it is
   * ignored and the page scrolls while the user is trying to zoom. A
   * non-passive listener is the only way to own the gesture.
   */
  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return
    const onWheel = (event: WheelEvent) => {
      // Before the first zoom the page must still scroll normally; only once
      // the user is inside the image does the wheel belong to the viewer.
      if (zoom <= 1 && event.deltaY > 0) return
      event.preventDefault()
      zoomBy(event.deltaY < 0 ? 1.18 : 1 / 1.18)
    }
    frame.addEventListener('wheel', onWheel, { passive: false })
    return () => frame.removeEventListener('wheel', onWheel)
    // `raster` is a dependency because the frame element does not exist until
    // the decode finishes; without it the listener would never attach.
  }, [zoom, zoomBy, raster])

  if (loading) {
    return (
      <div className="sq-raster">
        <div className="sq-raster__frame sq-raster__frame--loading">
          <Skeleton height="100%" radius={0} />
        </div>
      </div>
    )
  }

  if (error || !raster) {
    return (
      <div className="sq-raster">
        <div className="sq-raster__frame">
          <StateBlock
            icon={<AlertIcon size={18} />}
            tone="warning"
            title="This raster could not be displayed"
            body={
              <>
                <p>{error ?? 'The file could not be decoded in the browser.'}</p>
                <p>It can still be downloaded and opened in a GIS.</p>
              </>
            }
          />
        </div>
      </div>
    )
  }

  const reduced = raster.sourceWidth > raster.width

  return (
    <div className="sq-raster">
      <div
        ref={frameRef}
        className={`sq-raster__frame${zoom > 1 ? ' sq-raster__frame--zoomed' : ''}`}
        style={
          {
            aspectRatio: `${raster.width} / ${raster.height}`,
            '--sq-raster-ar': raster.width / raster.height,
          } as CSSProperties
        }
        onPointerMove={(event) => {
          const drag = dragRef.current
          if (drag && drag.id === event.pointerId) {
            setOffset((current) =>
              clampOffset(
                {
                  x: current.x + (event.clientX - drag.x),
                  y: current.y + (event.clientY - drag.y),
                },
                zoom,
              ),
            )
            dragRef.current = { x: event.clientX, y: event.clientY, id: event.pointerId }
            return
          }
          readProbe(event)
        }}
        onPointerDown={(event) => {
          if (zoom <= 1) return
          dragRef.current = { x: event.clientX, y: event.clientY, id: event.pointerId }
          event.currentTarget.setPointerCapture(event.pointerId)
        }}
        onPointerUp={(event) => {
          dragRef.current = null
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId)
          }
        }}
        onPointerLeave={() => {
          dragRef.current = null
          setProbe(null)
        }}
      >
        <canvas
          ref={canvasRef}
          className="sq-raster__canvas"
          style={{
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
            imageRendering: zoom > 2 ? 'pixelated' : 'auto',
          }}
          aria-label={caption ?? 'Analysis result raster'}
          role="img"
        />

        <div className="sq-raster__controls">
          <IconButton
            label="Zoom in"
            size="sm"
            outlined
            onClick={() => zoomBy(1.5)}
            disabled={zoom >= MAX_ZOOM}
          >
            <ZoomInIcon size={14} />
          </IconButton>
          <IconButton
            label="Zoom out"
            size="sm"
            outlined
            onClick={() => zoomBy(1 / 1.5)}
            disabled={zoom <= MIN_ZOOM}
          >
            <ZoomOutIcon size={14} />
          </IconButton>
          <IconButton
            label="Reset view"
            size="sm"
            outlined
            onClick={reset}
            disabled={zoom === 1 && offset.x === 0 && offset.y === 0}
          >
            <ResetIcon size={14} />
          </IconButton>
        </div>

        {probe ? (
          <div className="sq-raster__probe sq-mono">
            <span>{valueLabel ?? indexName ?? 'value'}</span>
            <strong>{formatIndex(probe.value)}</strong>
            <span className="sq-raster__probe-pixel">
              {probe.x}, {probe.y}
            </span>
          </div>
        ) : null}
      </div>

      <div className="sq-raster__legend">
        <div
          className="sq-raster__ramp"
          style={{ background: rampGradient(ramp) }}
          aria-hidden="true"
        />
        <div className="sq-raster__scale sq-mono">
          <span>{formatIndex(domain.low, 2)}</span>
          <span>{formatIndex(ramp.centre, 2)}</span>
          <span>{formatIndex(domain.high, 2)}</span>
        </div>
      </div>

      <p className="sq-raster__caption">
        {caption}
        {reduced ? (
          <>
            {caption ? ' · ' : ''}
            Shown at {raster.width} x {raster.height} of {raster.sourceWidth} x{' '}
            {raster.sourceHeight} px. Download for the full resolution.
          </>
        ) : null}
      </p>
    </div>
  )
}
