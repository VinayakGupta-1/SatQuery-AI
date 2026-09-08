import { useEffect, useState } from 'react'

/**
 * Decoding the rasters the backend produces, in the browser.
 *
 * SatQuery returns its results as GeoTIFF - a float32 index raster, or a uint8
 * classification. No browser can display either natively, so the alternative
 * to decoding here would be to show the user a download link and no picture at
 * all. `geotiff` reads the file, and the viewer colours it.
 *
 * The decode is deliberately bounded: `readRasters` is asked for a reduced
 * grid rather than the full scene, so a 10980x10980 Sentinel-2 tile becomes a
 * texture the size of the panel it is drawn into instead of 480 MB of floats.
 */

export interface DecodedRaster {
  width: number
  height: number
  /** One band, row-major, already reduced to the requested size. */
  values: Float32Array
  /** Value written for pixels that could not be computed. */
  nodata: number | null
  /** Range across valid pixels only. */
  min: number
  max: number
  /** Dimensions of the source file, before reduction. */
  sourceWidth: number
  sourceHeight: number
}

export interface RasterLoadState {
  raster: DecodedRaster | null
  loading: boolean
  error: string | null
}

/** The longest edge the decoder is allowed to produce. */
const MAX_EDGE = 1024

function isNodata(value: number, nodata: number | null): boolean {
  if (!Number.isFinite(value)) return true
  if (nodata === null) return false
  return Number.isNaN(nodata) ? Number.isNaN(value) : value === nodata
}

/**
 * Fetch and decode a single-band GeoTIFF.
 *
 * `geotiff` is imported dynamically: it is the largest dependency in the
 * application and only the result screens need it, so it stays out of the
 * initial bundle.
 */
export function useGeoTiff(url: string | null): RasterLoadState {
  const [state, setState] = useState<RasterLoadState>({
    raster: null,
    loading: Boolean(url),
    error: null,
  })

  useEffect(() => {
    if (!url) {
      setState({ raster: null, loading: false, error: null })
      return
    }

    let cancelled = false
    const controller = new AbortController()
    setState({ raster: null, loading: true, error: null })

    const load = async () => {
      const { fromArrayBuffer } = await import('geotiff')

      const response = await fetch(url, { signal: controller.signal })
      if (!response.ok) {
        throw new Error(`The result raster could not be downloaded (HTTP ${response.status}).`)
      }
      const buffer = await response.arrayBuffer()

      const tiff = await fromArrayBuffer(buffer)
      const image = await tiff.getImage()
      const sourceWidth = image.getWidth()
      const sourceHeight = image.getHeight()

      const scale = Math.min(1, MAX_EDGE / Math.max(sourceWidth, sourceHeight))
      const width = Math.max(1, Math.round(sourceWidth * scale))
      const height = Math.max(1, Math.round(sourceHeight * scale))

      const rasters = await image.readRasters({
        width,
        height,
        samples: [0],
        interleave: false,
      })

      const band = (rasters as unknown as ArrayLike<number>[])[0]
      const nodata = image.getGDALNoData()
      const values = new Float32Array(width * height)

      let min = Number.POSITIVE_INFINITY
      let max = Number.NEGATIVE_INFINITY
      for (let index = 0; index < values.length; index += 1) {
        const value = Number(band[index])
        values[index] = value
        if (isNodata(value, nodata)) continue
        if (value < min) min = value
        if (value > max) max = value
      }

      if (min > max) {
        // Every pixel was nodata. A range of 0..1 keeps the viewer from
        // dividing by an infinite span; the panel reports the empty result.
        min = 0
        max = 1
      }

      return {
        width,
        height,
        values,
        nodata: nodata ?? null,
        min,
        max,
        sourceWidth,
        sourceHeight,
      } satisfies DecodedRaster
    }

    load()
      .then((raster) => {
        if (!cancelled) setState({ raster, loading: false, error: null })
      })
      .catch((cause: unknown) => {
        if (cancelled || controller.signal.aborted) return
        setState({
          raster: null,
          loading: false,
          error:
            cause instanceof Error
              ? cause.message
              : 'The result raster could not be read.',
        })
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [url])

  return state
}
