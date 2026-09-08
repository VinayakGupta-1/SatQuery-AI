import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { EarthScene, supportsWebGL } from './EarthScene'
import { usePrefersReducedMotion } from '../../hooks/useMediaQuery'
import './earth.css'

export interface EarthHandle {
  /** Fly to the surface. Resolves when the descent completes. */
  descend: (durationMs: number) => Promise<void>
}

interface EarthCanvasProps {
  ref?: Ref<EarthHandle>
}

/**
 * Mounts `EarthScene` and exposes its one imperative action.
 *
 * The scene is created in an effect and torn down with it, so a React strict
 * double-mount in development disposes the first renderer rather than leaking
 * a WebGL context.
 *
 * When WebGL is unavailable the component renders a flat CSS globe instead.
 * That fallback is not a placeholder: the sign-in screen still has a horizon,
 * and `descend` still resolves, so the flow behaves identically.
 */
export function EarthCanvas({ ref }: EarthCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const sceneRef = useRef<EarthScene | null>(null)
  const reducedMotion = usePrefersReducedMotion()
  const [webgl] = useState(supportsWebGL)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!webgl || !canvasRef.current) return
    const canvas = canvasRef.current
    let scene: EarthScene | null = null
    let cancelled = false

    // Building the textures is a few hundred milliseconds of synchronous work.
    // Deferring it past the first paint means the sign-in panel is on screen
    // and usable immediately, and the globe resolves into it a moment later -
    // rather than the whole page waiting on the globe.
    const timer = window.setTimeout(() => {
      if (cancelled) return
      try {
        scene = new EarthScene({
          canvas,
          reducedMotion,
          onReady: () => setReady(true),
        })
        sceneRef.current = scene
        scene.start()
      } catch {
        // A context that reports as available but cannot actually be created -
        // a software renderer under memory pressure, most often. Fall through
        // to the flat globe rather than showing an empty frame.
        setFailed(true)
      }
    }, 0)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
      scene?.dispose()
      sceneRef.current = null
    }
  }, [webgl, reducedMotion])

  useImperativeHandle(
    ref,
    () => ({
      descend: (durationMs: number) =>
        sceneRef.current?.descend(durationMs) ?? Promise.resolve(),
    }),
    [],
  )

  if (!webgl || failed) {
    return (
      <div className="sq-earth sq-earth--fallback" aria-hidden="true">
        <div className="sq-earth__flat" />
        <div className="sq-earth__flat-glow" />
      </div>
    )
  }

  return (
    <div className={`sq-earth${ready ? ' sq-earth--ready' : ''}`}>
      <canvas
        ref={canvasRef}
        className="sq-earth__canvas"
        /* The globe is decorative: it carries no information the panel beside
           it does not already state, and it is not a control. It is announced
           as an image with a label rather than exposed as an interactive
           widget nobody can operate from a keyboard. */
        role="img"
        aria-label="Interactive globe. Drag to rotate."
      />
    </div>
  )
}
