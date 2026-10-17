import { describe, expect, it } from 'vitest'
import {
  formatBytes,
  formatDate,
  formatIndex,
  formatLonLat,
  formatPercent,
} from './format'

describe('formatPercent', () => {
  it('turns a 0..1 fraction into a percentage', () => {
    expect(formatPercent(0.1234)).toBe('12.3%')
    expect(formatPercent(0.5, 0)).toBe('50%')
  })

  it('shows a dash for missing values rather than 0%', () => {
    expect(formatPercent(null)).toBe('--')
    expect(formatPercent(Number.NaN)).toBe('--')
  })
})

describe('formatIndex', () => {
  it('keeps the sign and three decimals', () => {
    expect(formatIndex(-0.13)).toBe('-0.130')
    expect(formatIndex(undefined)).toBe('--')
  })
})

describe('formatBytes', () => {
  it('picks a readable unit, with whole kilobytes and one decimal above', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('2 KB')
    expect(formatBytes(1.5 * 1024 * 1024)).toBe('1.5 MB')
    expect(formatBytes(512 * 1024 * 1024)).toBe('512 MB')
  })
})

describe('formatLonLat', () => {
  it('writes latitude first with hemispheres, as the backend narrates', () => {
    expect(formatLonLat([73.85, 18.52])).toBe('18.5200° N, 73.8500° E')
    expect(formatLonLat([-43.2, -22.9])).toBe('22.9000° S, 43.2000° W')
  })

  it('refuses incomplete coordinates', () => {
    expect(formatLonLat([73.85])).toBe('--')
    expect(formatLonLat(null)).toBe('--')
  })
})

describe('formatDate', () => {
  it('returns an unparseable value unchanged rather than "Invalid Date"', () => {
    expect(formatDate('not a date')).toBe('not a date')
    expect(formatDate(null)).toBe('--')
  })
})
