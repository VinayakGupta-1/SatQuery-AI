import { describe, expect, it } from 'vitest'
import { suggestionsFor } from './suggestions'
import type { CapabilitiesResponse } from '../../types/api'

function capabilities(executable: string[]): CapabilitiesResponse {
  return { executable } as CapabilitiesResponse
}

describe('suggestionsFor', () => {
  it('offers nothing before the capabilities are known', () => {
    expect(suggestionsFor(null)).toEqual([])
  })

  it('never offers a question the service cannot run', () => {
    const offered = suggestionsFor(capabilities(['ndvi', 'ndwi']), 10)
    expect(offered.length).toBeGreaterThan(0)
    expect(offered.every((entry) => ['ndvi', 'ndwi'].includes(entry.toolId))).toBe(true)
  })

  it('shows one example per capability before a second of any', () => {
    const offered = suggestionsFor(capabilities(['ndvi', 'change_detection', 'ndwi']), 3)
    expect(new Set(offered.map((entry) => entry.toolId)).size).toBe(3)
  })

  it('names a place when imagery will be fetched', () => {
    const offered = suggestionsFor(capabilities(['ndvi', 'sar_analysis']), 4, true)
    expect(offered.map((entry) => entry.text)).toContain(
      'How healthy is the vegetation in Pune?',
    )
    expect(offered.some((entry) => /this (scene|image)/.test(entry.text))).toBe(false)
  })
})
