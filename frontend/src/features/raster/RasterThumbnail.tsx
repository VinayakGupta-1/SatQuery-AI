import { useEffect, useRef } from 'react'
import { useRasterPreview } from './useRasterPreview'
import { FileIcon } from '../../components/icons'
import { Tooltip } from '../../components/ui'

interface RasterThumbnailProps {
  file: File
  /** Rendered edge length in pixels. */
  size?: number
  /** Skip the decode entirely - used for files already known to be wrong. */
  disabled?: boolean
}

/**
 * What the staged file actually looks like.
 *
 * A filename tells you nothing about whether you picked the right scene. This
 * decodes the GeoTIFF in the browser and draws it, so the imagery is visible
 * before a single byte is uploaded.
 *
 * Failure is quiet and non-blocking: a file that cannot be previewed still
 * uploads, because the server is the authority on whether it can be read.
 */
export function RasterThumbnail({
  file,
  size = 56,
  disabled = false,
}: RasterThumbnailProps) {
  const { preview, loading, error } = useRasterPreview(disabled ? null : file, size * 2)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !preview) return
    canvas.width = preview.width
    canvas.height = preview.height
    const context = canvas.getContext('2d')
    if (!context) return
    context.putImageData(
      new ImageData(preview.pixels, preview.width, preview.height),
      0,
      0,
    )
  }, [preview])

  const style = { width: size, height: size }

  if (disabled || error) {
    return (
      <span className="sq-thumb sq-thumb--empty" style={style} aria-hidden="true">
        <FileIcon size={Math.round(size * 0.36)} />
      </span>
    )
  }

  if (loading || !preview) {
    return (
      <span
        className="sq-thumb sq-thumb--loading"
        style={style}
        aria-label="Reading the raster"
      />
    )
  }

  const caption = `${preview.rendering}, ${preview.bandCount} band${
    preview.bandCount === 1 ? '' : 's'
  }${preview.bands.length > 0 ? ` (${preview.bands.join(', ')})` : ''}`

  return (
    <Tooltip text={caption}>
      <span className="sq-thumb" style={style}>
        <canvas
          ref={canvasRef}
          className="sq-thumb__canvas"
          role="img"
          aria-label={`Preview of ${file.name}: ${caption}`}
        />
      </span>
    </Tooltip>
  )
}
