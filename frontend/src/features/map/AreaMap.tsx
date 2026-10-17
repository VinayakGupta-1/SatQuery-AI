import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './map.css'

/** `[west, south, east, north]` in degrees, the order the backend uses. */
export type LonLatBox = [number, number, number, number]

interface AreaMapProps {
  /** The area to outline and frame, when there is one. */
  box?: readonly number[] | null
  /** When given, the map offers "Draw area" and reports the box drawn. */
  onPick?: (box: LonLatBox) => void
  /** Accessible description of what the map shows. */
  label: string
  height?: number
}

/** India, framed, for a map with nothing to show yet. */
const INDIA: L.LatLngBoundsExpression = [
  [6.5, 68.0],
  [35.5, 97.5],
]

const OUTLINE: L.PathOptions = {
  color: '#4fc3f7',
  weight: 2,
  fillColor: '#4fc3f7',
  fillOpacity: 0.12,
}

function toBounds(box: readonly number[]): L.LatLngBounds {
  const [west, south, east, north] = box
  return L.latLngBounds([south, west], [north, east])
}

function round(value: number): number {
  return Math.round(value * 10000) / 10000
}

/**
 * A basemap with the area of a question on it.
 *
 * Results use it to show where the numbers come from; the composer uses it to
 * let a person drag out the area they mean instead of typing coordinates.
 * Tiles are OpenStreetMap's, darkened to the workspace palette and attributed
 * on the map.
 */
export function AreaMap({ box, onPick, label, height = 260 }: AreaMapProps) {
  const container = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const outlineRef = useRef<L.Rectangle | null>(null)
  const pickRef = useRef(onPick)
  const [drawing, setDrawing] = useState(false)

  useEffect(() => {
    pickRef.current = onPick
  }, [onPick])

  // Create the map once.
  useEffect(() => {
    if (!container.current) return
    const map = L.map(container.current, {
      zoomControl: true,
      attributionControl: true,
      worldCopyJump: true,
    })
    // OpenStreetMap's own tiles need no key; light use with attribution is
    // within its tile policy. They are darkened in CSS to suit the workspace.
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map)
    map.fitBounds(INDIA)
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      outlineRef.current = null
    }
  }, [])

  // Outline and frame the box whenever it changes.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    outlineRef.current?.remove()
    outlineRef.current = null
    if (box && box.length === 4 && box.every(Number.isFinite)) {
      const bounds = toBounds(box)
      outlineRef.current = L.rectangle(bounds, OUTLINE).addTo(map)
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 })
    }
  }, [box])

  // Drag out a rectangle while drawing; pan normally otherwise.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !drawing) return
    map.dragging.disable()
    map.getContainer().style.cursor = 'crosshair'
    let start: L.LatLng | null = null
    let sketch: L.Rectangle | null = null

    const down = (event: L.LeafletMouseEvent) => {
      start = event.latlng
      sketch = L.rectangle(L.latLngBounds(start, start), { ...OUTLINE, dashArray: '4 4' }).addTo(map)
    }
    const move = (event: L.LeafletMouseEvent) => {
      if (start && sketch) sketch.setBounds(L.latLngBounds(start, event.latlng))
    }
    const up = (event: L.LeafletMouseEvent) => {
      if (!start) return
      const bounds = L.latLngBounds(start, event.latlng)
      sketch?.remove()
      start = null
      setDrawing(false)
      if (bounds.getNorth() - bounds.getSouth() < 1e-4 || bounds.getEast() - bounds.getWest() < 1e-4) {
        return // a click, not a drag
      }
      pickRef.current?.([
        round(bounds.getWest()),
        round(bounds.getSouth()),
        round(bounds.getEast()),
        round(bounds.getNorth()),
      ])
    }
    map.on('mousedown', down)
    map.on('mousemove', move)
    map.on('mouseup', up)
    return () => {
      map.off('mousedown', down)
      map.off('mousemove', move)
      map.off('mouseup', up)
      sketch?.remove()
      map.dragging.enable()
      map.getContainer().style.cursor = ''
    }
  }, [drawing])

  return (
    <div className="sq-areamap">
      <div
        ref={container}
        className="sq-areamap__canvas"
        style={{ height }}
        role="img"
        aria-label={label}
      />
      {onPick ? (
        <div className="sq-areamap__tools">
          <button
            type="button"
            className={`sq-btn sq-btn--sm ${drawing ? 'sq-btn--primary' : 'sq-btn--ghost'}`}
            onClick={() => setDrawing((value) => !value)}
          >
            {drawing ? 'Drag on the map…' : 'Draw area'}
          </button>
          <span className="sq-areamap__hint">
            {drawing
              ? 'Press and drag to outline the area, up to 20 km across is analysed at full detail.'
              : 'Pan and zoom to the place, then draw the area to analyse.'}
          </span>
        </div>
      ) : null}
    </div>
  )
}
