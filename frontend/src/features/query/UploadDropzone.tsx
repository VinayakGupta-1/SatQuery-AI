import { useRef, useState, type DragEvent } from 'react'
import { TrashIcon, UploadIcon } from '../../components/icons'
import { RasterThumbnail } from '../raster/RasterThumbnail'
import { IconButton, Notice, Tag } from '../../components/ui'
import { useWorkspace } from '../../context/workspaceContext'
import { useCapabilities } from '../../context/capabilitiesContext'
import { formatBytes } from '../../utils/format'

interface UploadDropzoneProps {
  /** `panel` is the full surface on the Imagery screen; `inline` sits under
   *  the composer and stays out of the way until it holds something. */
  variant?: 'panel' | 'inline'
}

/**
 * Staging rasters for the next analysis.
 *
 * Files are held in memory and sent with the query - the backend has no
 * separate upload endpoint and no dataset library, so there is nothing to
 * "upload to" ahead of asking a question. The screen says so plainly rather
 * than implying a persistent store that does not exist.
 */
export function UploadDropzone({ variant = 'panel' }: UploadDropzoneProps) {
  const { files, addFiles, removeFile, clearFiles } = useWorkspace()
  const { capabilities } = useCapabilities()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)

  const accepted = capabilities?.accepted_formats ?? []
  const maxImages = capabilities?.max_images_per_task ?? 8
  const rejected = files.filter((entry) => entry.problem)

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    if (event.dataTransfer.files.length > 0) addFiles(event.dataTransfer.files)
  }

  return (
    <div className={`sq-upload sq-upload--${variant}`}>
      <div
        className={`sq-upload__zone${dragging ? ' sq-upload__zone--active' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accepted.join(',')}
          className="sq-sr-only"
          id="sq-upload-input"
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files)
            event.target.value = ''
          }}
        />

        <UploadIcon size={22} className="sq-upload__glyph" />
        <div className="sq-upload__copy">
          <label htmlFor="sq-upload-input" className="sq-upload__prompt">
            Drop imagery here, or <span className="sq-upload__browse">browse</span>
          </label>
          <p className="sq-upload__hint">
            {accepted.length > 0
              ? `${accepted.join(', ')} · up to ${maxImages} rasters · max ${formatBytes(
                  capabilities?.max_upload_bytes,
                )} each`
              : 'GeoTIFF and JPEG 2000 rasters'}
          </p>
        </div>
      </div>

      {files.length > 0 ? (
        <>
          <ul className="sq-upload__list">
            {files.map((entry) => (
              <li
                key={entry.id}
                className={`sq-upload__item${entry.problem ? ' sq-upload__item--bad' : ''}`}
              >
                {/* Decoded in the browser: nothing is uploaded to draw this. */}
                <RasterThumbnail
                  file={entry.file}
                  size={variant === 'panel' ? 72 : 52}
                  disabled={Boolean(entry.problem)}
                />
                <div className="sq-upload__item-body">
                  <span className="sq-upload__item-name">{entry.name}</span>
                  <span className="sq-upload__item-meta">
                    {formatBytes(entry.size)}
                    {entry.problem ? ` · ${entry.problem}` : ''}
                  </span>
                </div>
                {entry.problem ? <Tag tone="danger">Rejected</Tag> : null}
                <IconButton
                  label={`Remove ${entry.name}`}
                  size="sm"
                  onClick={() => removeFile(entry.id)}
                >
                  <TrashIcon size={14} />
                </IconButton>
              </li>
            ))}
          </ul>

          <div className="sq-upload__foot">
            <span className="sq-upload__count">
              {files.length - rejected.length} ready
              {rejected.length > 0 ? `, ${rejected.length} rejected` : ''}
            </span>
            <button type="button" className="sq-upload__clear" onClick={clearFiles}>
              Remove all
            </button>
          </div>
        </>
      ) : null}

      {files.length > maxImages ? (
        <Notice tone="warning" title="More rasters than the service accepts">
          This deployment analyses at most {maxImages} images per task. Remove some,
          or combine the bands into one scene below.
        </Notice>
      ) : null}
    </div>
  )
}
