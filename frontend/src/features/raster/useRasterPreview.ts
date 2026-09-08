import { useEffect, useState } from 'react'

/**
 * A viewable picture of a raster the user has staged but not yet sent.
 *
 * A satellite scene is a multi-band uint16 GeoTIFF: the browser cannot display
 * one, and a filename is a poor substitute for seeing what you attached. So
 * the file is decoded locally - it never leaves the machine for this - and
 * rendered as a natural-colour composite where the bands allow it, or as a
 * stretched greyscale band where they do not.
 *
 * Two things make this cheap enough to do on every staged file:
 *
 * `fromBlob` reads the file through range requests rather than loading it into
 * memory, and `readRasters` is asked for a thumbnail-sized grid, so a 10980 px
 * Sentinel-2 tile is decoded straight down to the size it will be drawn at.
 */

export interface RasterPreview {
  width: number
  height: number
  /** RGBA, ready for `putImageData`. Backed by a plain (non-shared) buffer,
   *  which is what the `ImageData` constructor requires. */
  pixels: Uint8ClampedArray<ArrayBuffer>
  /** Dimensions of the source file. */
  sourceWidth: number
  sourceHeight: number
  bandCount: number
  /** What the preview is showing, for the caption. */
  rendering: 'natural colour' | 'false colour' | 'single band'
  /** Band names, when the file declares them. */
  bands: string[]
}

export interface PreviewState {
  preview: RasterPreview | null
  loading: boolean
  /** A short, user-facing reason there is no picture. */
  error: string | null
}

/**
 * Files above this are not previewed.
 *
 * A thumbnail-sized read still has to touch every strip of an uncompressed
 * scene, and spending that on a half-gigabyte upload would stall the composer
 * for no good reason. The upload itself is unaffected.
 */
const MAX_PREVIEW_BYTES = 220 * 1024 * 1024

/** Band-name vocabulary, for choosing which samples to draw.
 *
 *  This is a *display* heuristic only. The authoritative band resolution -- the
 *  one an index is actually computed from -- happens on the server, which is
 *  sensor-aware; `B5` is red-edge on Sentinel-2 and near-infrared on Landsat-8,
 *  and that distinction matters for arithmetic but not for a thumbnail. */
const BAND_ALIASES: Record<string, 'red' | 'green' | 'blue' | 'nir'> = {
  red: 'red',
  green: 'green',
  blue: 'blue',
  nir: 'nir',
  near_infrared: 'nir',
  b2: 'blue',
  b02: 'blue',
  b3: 'green',
  b03: 'green',
  b4: 'red',
  b04: 'red',
  b8: 'nir',
  b08: 'nir',
}

function classify(name: string | undefined): 'red' | 'green' | 'blue' | 'nir' | null {
  if (!name) return null
  const key = name.trim().toLowerCase().replace(/[\s-]+/g, '_')
  return BAND_ALIASES[key] ?? null
}

/**
 * Contrast stretch bounds from the 2nd and 98th percentile.
 *
 * Raw digital numbers occupy a narrow part of the uint16 range, so a linear
 * map of 0..65535 renders every scene as near-black. Clipping the tails is
 * what makes the picture look like the ground.
 */
function stretchBounds(values: ArrayLike<number>, skip: (value: number) => boolean) {
  const sample: number[] = []
  const stride = Math.max(1, Math.floor(values.length / 4096))
  for (let index = 0; index < values.length; index += stride) {
    const value = Number(values[index])
    if (Number.isFinite(value) && !skip(value)) sample.push(value)
  }
  if (sample.length === 0) return { low: 0, high: 1 }
  sample.sort((a, b) => a - b)
  const low = sample[Math.floor(sample.length * 0.02)]
  const high = sample[Math.floor(sample.length * 0.98)]
  return { low, high: high > low ? high : low + 1 }
}

export function useRasterPreview(
  file: File | null,
  maxEdge = 96,
): PreviewState {
  const [state, setState] = useState<PreviewState>({
    preview: null,
    loading: Boolean(file),
    error: null,
  })

  useEffect(() => {
    if (!file) {
      setState({ preview: null, loading: false, error: null })
      return
    }
    if (file.size > MAX_PREVIEW_BYTES) {
      setState({ preview: null, loading: false, error: 'Too large to preview' })
      return
    }

    let cancelled = false
    setState({ preview: null, loading: true, error: null })

    const load = async (): Promise<RasterPreview> => {
      const { fromBlob } = await import('geotiff')
      const tiff = await fromBlob(file)
      const image = await tiff.getImage()

      const sourceWidth = image.getWidth()
      const sourceHeight = image.getHeight()
      const bandCount = image.getSamplesPerPixel()

      const scale = Math.min(1, maxEdge / Math.max(sourceWidth, sourceHeight))
      const width = Math.max(1, Math.round(sourceWidth * scale))
      const height = Math.max(1, Math.round(sourceHeight * scale))

      // Band descriptions, where GDAL wrote them.
      const bands: string[] = []
      for (let index = 0; index < bandCount; index += 1) {
        const meta = image.getGDALMetadata(index) as
          | Record<string, string>
          | undefined
        bands.push(meta?.DESCRIPTION ?? '')
      }

      const roles = bands.map(classify)
      const find = (role: string) => roles.findIndex((entry) => entry === role)

      let samples: number[]
      let rendering: RasterPreview['rendering']

      const red = find('red')
      const green = find('green')
      const blue = find('blue')

      if (red >= 0 && green >= 0 && blue >= 0) {
        samples = [red, green, blue]
        rendering = 'natural colour'
      } else if (bandCount >= 3) {
        // No usable names. The first three samples are drawn in order, which
        // is right for an ordinary RGB GeoTIFF and merely indicative for a
        // multispectral one - hence the honest label.
        samples = [0, 1, 2]
        rendering = 'false colour'
      } else {
        samples = [0]
        rendering = 'single band'
      }

      const rasters = (await image.readRasters({
        width,
        height,
        samples,
        interleave: false,
      })) as unknown as ArrayLike<number>[]

      const nodata = image.getGDALNoData()
      const isMissing = (value: number) =>
        !Number.isFinite(value) ||
        (nodata !== null &&
          (Number.isNaN(nodata) ? Number.isNaN(value) : value === nodata))

      /*
       * One stretch across all three channels, not one per channel.
       *
       * Stretching each band to its own full range is a colour balance, not a
       * natural-colour rendering: it discards the relationship between the
       * bands, so a scene with little variance in blue comes out strongly
       * tinted. A shared window preserves what the sensor actually saw, which
       * is what the label on this preview claims.
       */
      const shared = stretchBounds(
        rasters.length > 1
          ? rasters.flatMap((band) =>
              Array.from({ length: Math.min(band.length, 2048) }, (_, index) =>
                Number(band[Math.floor((index * band.length) / 2048)]),
              ),
            )
          : rasters[0],
        isMissing,
      )
      const channels = rasters.map((band) => ({ data: band, ...shared }))

      const pixels = new Uint8ClampedArray(width * height * 4)
      for (let index = 0; index < width * height; index += 1) {
        const target = index * 4
        let visible = true
        const rgb = [0, 0, 0]

        for (let channel = 0; channel < 3; channel += 1) {
          // A single-band preview writes the same value to all three.
          const source = channels[Math.min(channel, channels.length - 1)]
          const raw = Number(source.data[index])
          if (isMissing(raw)) {
            visible = false
            break
          }
          rgb[channel] =
            ((raw - source.low) / (source.high - source.low)) * 255
        }

        if (!visible) {
          pixels[target + 3] = 0
          continue
        }
        pixels[target] = rgb[0]
        pixels[target + 1] = rgb[1]
        pixels[target + 2] = rgb[2]
        pixels[target + 3] = 255
      }

      return {
        width,
        height,
        pixels,
        sourceWidth,
        sourceHeight,
        bandCount,
        rendering,
        bands: bands.filter(Boolean),
      }
    }

    load()
      .then((preview) => {
        if (!cancelled) setState({ preview, loading: false, error: null })
      })
      .catch(() => {
        if (!cancelled) {
          // The file is still uploadable; only the picture failed. The server
          // remains the authority on whether it can be read at all.
          setState({ preview: null, loading: false, error: 'No preview' })
        }
      })

    return () => {
      cancelled = true
    }
  }, [file, maxEdge])

  return state
}
