import { beforeEach, describe, expect, it, vi } from 'vitest'

const postForm = vi.fn()

vi.mock('./http', () => ({
  get: vi.fn(),
  postForm: (path: string, form: FormData) => postForm(path, form),
}))

const { analyze, validateRequest } = await import('./satquery')

function sentForm(): FormData {
  return postForm.mock.calls[postForm.mock.calls.length - 1][1] as FormData
}

describe('the analysis request body', () => {
  beforeEach(() => postForm.mockReset())

  it('sends no files and the location when imagery is to be fetched', async () => {
    await analyze({ query: 'Vegetation?', files: [], location: '  Pune  ' })
    const form = sentForm()
    expect(postForm.mock.calls[0][0]).toBe('/api/tasks')
    expect(form.get('query')).toBe('Vegetation?')
    expect(form.getAll('files')).toHaveLength(0)
    expect(form.get('location')).toBe('Pune')
  })

  it('leaves the location out when imagery is attached', async () => {
    const file = new File(['II*'], 'scene.tif', { type: 'image/tiff' })
    await analyze({ query: 'NDVI', files: [file], location: 'Pune' })
    const form = sentForm()
    expect(form.getAll('files')).toHaveLength(1)
    expect(form.get('location')).toBeNull()
  })

  it('leaves out a blank location and empty parameters', async () => {
    await analyze({ query: 'NDVI', files: [], location: '   ', parameters: {} })
    const form = sentForm()
    expect(form.get('location')).toBeNull()
    expect(form.get('parameters')).toBeNull()
  })

  it('serialises explicit parameters for analysis but not for a dry run', async () => {
    const file = new File(['II*'], 'scene.tif')
    await analyze({ query: 'NDVI', files: [file], parameters: { mask_band: 'SCL' } })
    expect(sentForm().get('parameters')).toBe('{"mask_band":"SCL"}')

    await validateRequest({ query: 'NDVI', files: [file], parameters: { mask_band: 'SCL' } })
    expect(postForm.mock.calls[1][0]).toBe('/api/tasks/validate')
    expect(sentForm().get('parameters')).toBeNull()
  })
})
