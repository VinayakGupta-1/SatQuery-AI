/**
 * The interactive Earth.
 *
 * A self-contained three.js scene with no React inside it: it owns a canvas,
 * a render loop and its own disposal. `EarthCanvas` mounts it. Keeping the
 * boundary here means React never re-renders anything on a per-frame basis.
 *
 * What is on screen:
 *   - the globe, shaded from real coastlines (see `earthTextures.ts`)
 *   - a cloud shell rotating slightly faster than the surface
 *   - an atmospheric rim, drawn as a back-facing fresnel shell
 *   - one inclined orbit carrying a single satellite
 *   - a starfield
 *
 * Performance is bounded deliberately: device pixel ratio is capped, the loop
 * stops when the tab is hidden or the canvas leaves the viewport, and every
 * geometry, material and texture is disposed on teardown.
 */

import * as THREE from 'three'
import {
  buildAlbedoTexture,
  buildCloudTexture,
  buildSpecularTexture,
} from './earthTextures'

const EARTH_RADIUS = 1
/** Far enough that the globe reads as a body in space rather than a wall. */
const IDLE_CAMERA_Z = 4.35
const ORBIT_RADIUS = 1.42

/** Camera distance at the end of the descent - just above the surface. */
const SURFACE_CAMERA_Z = 1.04

export interface EarthSceneOptions {
  canvas: HTMLCanvasElement
  /** Suppress idle rotation and shorten the descent. */
  reducedMotion: boolean
  /** Called once the textures are built and the first frame is drawn. */
  onReady?: () => void
}

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
}

/** Slow at first, then a committed acceleration towards the surface. */
function easeInExpo(t: number): number {
  return t === 0 ? 0 : 2 ** (10 * t - 10)
}

export class EarthScene {
  private readonly renderer: THREE.WebGLRenderer
  private readonly scene: THREE.Scene
  private readonly camera: THREE.PerspectiveCamera
  /** Carries the axial tilt. Never spun, so the pole stays put in view. */
  private readonly axis: THREE.Group
  /** Spun about its own axis. Everything on the surface lives here. */
  private readonly globe: THREE.Group
  private readonly earth: THREE.Mesh
  private readonly clouds: THREE.Mesh
  private readonly atmosphere: THREE.Mesh
  private readonly orbit: THREE.Group
  private readonly satellite: THREE.Mesh
  private readonly stars: THREE.Points
  private readonly disposables: { dispose(): void }[] = []

  private readonly canvas: HTMLCanvasElement
  private readonly reducedMotion: boolean

  private frame = 0
  private running = false
  private lastTime = 0
  private clock = 0

  /** Drag state. */
  private dragging = false
  private pointerId: number | null = null
  private lastPointer = { x: 0, y: 0 }
  private velocity = { x: 0, y: 0 }
  private tilt = 0.12

  /** Descent state, 0 = in orbit, 1 = at the surface. */
  private descent = 0
  private descentStart = 0
  private descentDuration = 0
  private descentResolve: (() => void) | null = null

  private resizeObserver: ResizeObserver | null = null
  private intersectionObserver: IntersectionObserver | null = null
  private visible = true
  private onScreen = true

  constructor(options: EarthSceneOptions) {
    this.canvas = options.canvas
    this.reducedMotion = options.reducedMotion

    this.renderer = new THREE.WebGLRenderer({
      canvas: options.canvas,
      antialias: window.devicePixelRatio < 2,
      alpha: true,
      powerPreference: 'high-performance',
    })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setClearColor(0x000000, 0)
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 1.24

    this.scene = new THREE.Scene()
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100)
    this.camera.position.set(0, 0, IDLE_CAMERA_Z)

    // ---- lighting ---------------------------------------------------------
    // The sun sits over the camera's left shoulder, so most of what faces the
    // viewer is daylit and the terminator falls near the right limb. Enough
    // fill that the night side stays legible rather than black, and a cool rim
    // from behind to separate the globe from space.
    const sun = new THREE.DirectionalLight(0xfff2dd, 3.3)
    // Far enough round to throw a terminator across the right of the disc.
    // A globe lit flat from the camera reads as a printed ball.
    sun.position.set(-2.3, 0.8, 1.9)
    this.scene.add(sun)

    const fill = new THREE.AmbientLight(0x4a6280, 0.45)
    this.scene.add(fill)

    const rim = new THREE.DirectionalLight(0x6cb6cc, 0.5)
    rim.position.set(2.6, -0.8, -2.4)
    this.scene.add(rim)

    // ---- globe ------------------------------------------------------------
    // Two nested groups, deliberately. If the axial tilt and the spin share
    // one transform, spinning swings the pole through the view and the globe
    // ends up staring at the camera down its own axis. Separating them keeps
    // the tilt fixed in view space while the surface turns underneath it.
    this.axis = new THREE.Group()
    this.axis.rotation.z = -0.41 // axial tilt, roughly
    this.axis.rotation.x = this.tilt
    this.scene.add(this.axis)

    this.globe = new THREE.Group()
    // At rotation.y = 0 the sphere's UV mapping puts 90 degrees west toward
    // the camera. Rotating by this much brings Europe, Africa and the Middle
    // East into view instead, which is a more legible face to open on.
    this.globe.rotation.y = -1.92
    this.axis.add(this.globe)

    const albedo = buildAlbedoTexture(2048)
    const specular = buildSpecularTexture(1024)
    const cloudMap = buildCloudTexture(1024)
    this.disposables.push(albedo, specular, cloudMap)

    const earthGeometry = new THREE.SphereGeometry(EARTH_RADIUS, 96, 96)
    const earthMaterial = new THREE.MeshPhongMaterial({
      map: albedo,
      specularMap: specular,
      // Restrained on purpose: a strong ocean highlight on a sphere this size
      // reads as a lens flare rather than as water.
      specular: new THREE.Color(0x1d2b36),
      shininess: 11,
    })
    this.earth = new THREE.Mesh(earthGeometry, earthMaterial)
    this.globe.add(this.earth)
    this.disposables.push(earthGeometry, earthMaterial)

    const cloudGeometry = new THREE.SphereGeometry(EARTH_RADIUS * 1.012, 64, 64)
    const cloudMaterial = new THREE.MeshLambertMaterial({
      map: cloudMap,
      transparent: true,
      opacity: 0.46,
      depthWrite: false,
    })
    this.clouds = new THREE.Mesh(cloudGeometry, cloudMaterial)
    this.globe.add(this.clouds)
    this.disposables.push(cloudGeometry, cloudMaterial)

    // ---- atmosphere -------------------------------------------------------
    // A back-facing shell whose opacity follows a fresnel term, so the rim
    // glows and the centre stays clear. Additive, and deliberately faint.
    const atmosphereGeometry = new THREE.SphereGeometry(EARTH_RADIUS * 1.16, 64, 64)
    const atmosphereMaterial = new THREE.ShaderMaterial({
      transparent: true,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      uniforms: {
        uColour: { value: new THREE.Color(0x4e9fd4) },
        uIntensity: { value: 1 },
      },
      vertexShader: /* glsl */ `
        varying vec3 vNormal;
        varying vec3 vView;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
          vView = normalize(-viewPosition.xyz);
          gl_Position = projectionMatrix * viewPosition;
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 uColour;
        uniform float uIntensity;
        varying vec3 vNormal;
        varying vec3 vView;
        void main() {
          float fresnel = pow(1.0 - abs(dot(vNormal, vView)), 3.2);
          gl_FragColor = vec4(uColour, fresnel * 0.85 * uIntensity);
        }
      `,
    })
    this.atmosphere = new THREE.Mesh(atmosphereGeometry, atmosphereMaterial)
    this.scene.add(this.atmosphere)
    this.disposables.push(atmosphereGeometry, atmosphereMaterial)

    // ---- orbit and satellite ---------------------------------------------
    this.orbit = new THREE.Group()
    this.orbit.rotation.set(1.05, 0.35, 0.42)
    this.scene.add(this.orbit)

    const orbitGeometry = new THREE.TorusGeometry(ORBIT_RADIUS, 0.0022, 6, 220)
    const orbitMaterial = new THREE.MeshBasicMaterial({
      color: 0xc9a45c,
      transparent: true,
      opacity: 0.24,
    })
    const orbitRing = new THREE.Mesh(orbitGeometry, orbitMaterial)
    this.orbit.add(orbitRing)
    this.disposables.push(orbitGeometry, orbitMaterial)

    const satelliteGeometry = new THREE.OctahedronGeometry(0.019, 0)
    const satelliteMaterial = new THREE.MeshBasicMaterial({ color: 0xc9a45c })
    this.satellite = new THREE.Mesh(satelliteGeometry, satelliteMaterial)
    this.satellite.position.set(ORBIT_RADIUS, 0, 0)
    this.orbit.add(this.satellite)
    this.disposables.push(satelliteGeometry, satelliteMaterial)

    // ---- starfield --------------------------------------------------------
    this.stars = EarthScene.buildStars(1100)
    this.scene.add(this.stars)
    this.disposables.push(this.stars.geometry, this.stars.material as THREE.Material)

    this.attachPointer()
    this.observe()
    this.resize()
    this.renderFrame()
    options.onReady?.()
  }

  /* ---------------------------------------------------------------------- */
  /* Construction helpers                                                    */
  /* ---------------------------------------------------------------------- */

  private static buildStars(count: number): THREE.Points {
    const positions = new Float32Array(count * 3)
    const colours = new Float32Array(count * 3)

    for (let index = 0; index < count; index += 1) {
      // Uniform on a sphere shell, well outside the globe.
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      const radius = 22 + Math.random() * 16
      positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta)
      positions[index * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta)
      positions[index * 3 + 2] = radius * Math.cos(phi)

      // Most stars are white; a few take a faint blue or amber cast.
      const warmth = Math.random()
      const brightness = 0.45 + Math.random() * 0.55
      colours[index * 3] = brightness * (warmth > 0.86 ? 1 : 0.9)
      colours[index * 3 + 1] = brightness * 0.92
      colours[index * 3 + 2] = brightness * (warmth < 0.14 ? 1 : 0.86)
    }

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geometry.setAttribute('color', new THREE.BufferAttribute(colours, 3))

    const material = new THREE.PointsMaterial({
      size: 0.09,
      sizeAttenuation: true,
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
    })
    return new THREE.Points(geometry, material)
  }

  /* ---------------------------------------------------------------------- */
  /* Interaction                                                             */
  /* ---------------------------------------------------------------------- */

  private attachPointer(): void {
    const canvas = this.canvas
    canvas.style.touchAction = 'none'

    canvas.addEventListener('pointerdown', this.onPointerDown)
    canvas.addEventListener('pointermove', this.onPointerMove)
    canvas.addEventListener('pointerup', this.onPointerUp)
    canvas.addEventListener('pointercancel', this.onPointerUp)
    canvas.addEventListener('lostpointercapture', this.onPointerUp)
  }

  private onPointerDown = (event: PointerEvent): void => {
    if (this.descent > 0) return
    this.dragging = true
    this.pointerId = event.pointerId
    this.lastPointer = { x: event.clientX, y: event.clientY }
    this.velocity = { x: 0, y: 0 }
    this.canvas.setPointerCapture(event.pointerId)
    this.canvas.style.cursor = 'grabbing'
  }

  private onPointerMove = (event: PointerEvent): void => {
    if (!this.dragging || event.pointerId !== this.pointerId) return
    const dx = event.clientX - this.lastPointer.x
    const dy = event.clientY - this.lastPointer.y
    this.lastPointer = { x: event.clientX, y: event.clientY }

    // Scale by viewport width so a drag feels the same on any screen size.
    const scale = 3.4 / Math.max(this.canvas.clientWidth, 1)
    this.globe.rotation.y += dx * scale
    this.tilt = THREE.MathUtils.clamp(this.tilt + dy * scale * 0.7, -0.9, 0.9)
    this.velocity = { x: dx * scale, y: dy * scale }
  }

  private onPointerUp = (event: PointerEvent): void => {
    if (event.pointerId !== this.pointerId) return
    this.dragging = false
    this.pointerId = null
    this.canvas.style.cursor = 'grab'
    if (this.canvas.hasPointerCapture(event.pointerId)) {
      this.canvas.releasePointerCapture(event.pointerId)
    }
  }

  /* ---------------------------------------------------------------------- */
  /* Lifecycle                                                               */
  /* ---------------------------------------------------------------------- */

  private observe(): void {
    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(this.canvas)

    // Stop rendering when the canvas scrolls away or the tab is hidden.
    this.intersectionObserver = new IntersectionObserver(
      ([entry]) => {
        this.onScreen = entry.isIntersecting
        this.syncLoop()
      },
      { threshold: 0 },
    )
    this.intersectionObserver.observe(this.canvas)

    document.addEventListener('visibilitychange', this.onVisibilityChange)
  }

  private onVisibilityChange = (): void => {
    this.visible = !document.hidden
    this.syncLoop()
  }

  private syncLoop(): void {
    const shouldRun = this.visible && this.onScreen
    if (shouldRun && !this.running) this.start()
    else if (!shouldRun && this.running) this.pause()
  }

  private resize(): void {
    const width = this.canvas.clientWidth || 1
    const height = this.canvas.clientHeight || 1
    this.renderer.setSize(width, height, false)
    this.camera.aspect = width / height
    // On a portrait or narrow canvas the globe must still fit: widening the
    // field of view is cheaper than moving the camera and keeps the framing.
    this.camera.fov = width / height < 1 ? 52 : 38
    this.camera.updateProjectionMatrix()
    this.renderFrame()
  }

  start(): void {
    if (this.running) return
    this.running = true
    this.lastTime = performance.now()
    const loop = (now: number) => {
      if (!this.running) return
      const delta = Math.min((now - this.lastTime) / 1000, 0.05)
      this.lastTime = now
      this.update(delta, now)
      this.renderFrame()
      this.frame = requestAnimationFrame(loop)
    }
    this.frame = requestAnimationFrame(loop)
  }

  pause(): void {
    this.running = false
    cancelAnimationFrame(this.frame)
  }

  /* ---------------------------------------------------------------------- */
  /* Frame                                                                   */
  /* ---------------------------------------------------------------------- */

  private update(delta: number, now: number): void {
    this.clock += delta

    if (this.descentDuration > 0) {
      this.updateDescent(now)
    }

    if (!this.dragging) {
      // Inertia from the last drag, then a slow idle spin once it has decayed.
      const damping = 0.94 ** (delta * 60)
      this.velocity.x *= damping
      this.velocity.y *= damping
      this.globe.rotation.y += this.velocity.x

      if (!this.reducedMotion) {
        // The idle spin speeds up during the descent - the ground below the
        // camera should be moving as it arrives.
        const idle = 0.035 + this.descent * 0.09
        this.globe.rotation.y += idle * delta
      }
    }

    this.axis.rotation.x += (this.tilt - this.axis.rotation.x) * Math.min(1, delta * 6)

    if (!this.reducedMotion) {
      // Clouds lead the surface slightly; the difference is what sells them.
      this.clouds.rotation.y += 0.012 * delta
      this.orbit.rotation.z += 0.05 * delta

      const angle = this.clock * 0.42
      this.satellite.position.set(
        Math.cos(angle) * ORBIT_RADIUS,
        Math.sin(angle) * ORBIT_RADIUS,
        0,
      )
      this.satellite.rotation.x += delta * 0.8
      this.satellite.rotation.y += delta * 1.1

      this.stars.rotation.y += 0.004 * delta
    }
  }

  private updateDescent(now: number): void {
    const elapsed = now - this.descentStart
    const t = Math.min(1, elapsed / this.descentDuration)
    this.descent = t

    // Two phases: an ease towards the globe, then a committed dive. The
    // exponential term is what makes the last moments read as a descent
    // rather than as a zoom.
    const approach = easeInOutCubic(Math.min(1, t / 0.55))
    const dive = t > 0.45 ? easeInExpo((t - 0.45) / 0.55) : 0
    const distance =
      IDLE_CAMERA_Z -
      (IDLE_CAMERA_Z - 1.55) * approach -
      (1.55 - SURFACE_CAMERA_Z) * dive

    this.camera.position.z = Math.max(SURFACE_CAMERA_Z, distance)
    // Narrowing the field of view as the camera arrives flattens the horizon
    // into the overhead view a satellite actually has.
    this.camera.fov = THREE.MathUtils.lerp(
      this.camera.aspect < 1 ? 52 : 38,
      26,
      easeInOutCubic(t),
    )
    this.camera.updateProjectionMatrix()

    const material = this.atmosphere.material as THREE.ShaderMaterial
    material.uniforms.uIntensity.value = 1 + t * 2.4

    const clouds = this.clouds.material as THREE.MeshLambertMaterial
    clouds.opacity = 0.46 * (1 - Math.min(1, t * 1.35))

    const stars = this.stars.material as THREE.PointsMaterial
    stars.opacity = 0.85 * (1 - Math.min(1, t * 1.6))

    if (t >= 1 && this.descentResolve) {
      const resolve = this.descentResolve
      this.descentResolve = null
      this.descentDuration = 0
      resolve()
    }
  }

  private renderFrame(): void {
    this.renderer.render(this.scene, this.camera)
  }

  /* ---------------------------------------------------------------------- */
  /* Public control                                                          */
  /* ---------------------------------------------------------------------- */

  /**
   * Fly the camera from orbit down to the surface.
   *
   * Resolves when the descent finishes, so the caller can hand over to the
   * workspace at exactly the right moment rather than guessing with a timer.
   */
  descend(durationMs: number): Promise<void> {
    if (this.reducedMotion) {
      // Reduced motion still needs the camera to end up somewhere sensible for
      // the cross-fade, it just does not travel there.
      this.descent = 1
      this.camera.position.z = SURFACE_CAMERA_Z
      this.camera.updateProjectionMatrix()
      this.renderFrame()
      return Promise.resolve()
    }

    this.dragging = false
    this.descentStart = performance.now()
    this.descentDuration = durationMs
    this.start()
    return new Promise<void>((resolve) => {
      this.descentResolve = resolve
    })
  }

  dispose(): void {
    this.pause()
    this.descentResolve = null

    this.canvas.removeEventListener('pointerdown', this.onPointerDown)
    this.canvas.removeEventListener('pointermove', this.onPointerMove)
    this.canvas.removeEventListener('pointerup', this.onPointerUp)
    this.canvas.removeEventListener('pointercancel', this.onPointerUp)
    this.canvas.removeEventListener('lostpointercapture', this.onPointerUp)
    document.removeEventListener('visibilitychange', this.onVisibilityChange)

    this.resizeObserver?.disconnect()
    this.intersectionObserver?.disconnect()

    for (const item of this.disposables) item.dispose()
    this.renderer.dispose()
  }
}

/** Whether this browser can run the globe at all. */
export function supportsWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext('webgl2') || canvas.getContext('webgl')),
    )
  } catch {
    return false
  }
}
