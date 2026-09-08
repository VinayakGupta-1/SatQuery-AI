# SatQuery AI — frontend

The Earth-observation workspace: ask a question of satellite imagery in plain
language, and get an answer you can inspect.

React 19 + TypeScript + Vite. No UI framework, no component library, no CSS
framework — the design system in `src/styles/tokens.css` and the primitives in
`src/components/ui` are the whole of it.

## Running it

The frontend needs the backend running beside it.

```bash
# 1. the analysis service
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload            # http://127.0.0.1:8000

# 2. the workspace
cd frontend
npm install
npm run dev                              # http://localhost:5173
```

The dev server proxies `/api`, `/health` and `/capabilities` to
`http://127.0.0.1:8000`, so the browser stays same-origin and CORS never comes
up. Point it elsewhere with `VITE_DEV_BACKEND`.

For a build served from another origin, set `VITE_API_BASE_URL` and add the
frontend's origin to the backend's `SATQUERY_CORS_ORIGINS`.

```bash
npm run build       # tsc -b && vite build  ->  dist/
npm run preview     # serve the build
npm run lint
```

### Something to analyse

The repository ships a generator for a co-registered pair of synthetic
Sentinel-2-style scenes, so the whole flow can be exercised without hunting for
a real product first:

```bash
cd backend
python scripts/make_demo_rasters.py demo_data
```

They are synthetic but they are real GeoTIFFs — georeferenced, four-band,
band-named — so everything computed from them is a genuine computation. Upload
one and ask *"How healthy is the vegetation in this scene?"*, or upload both and
ask *"Compare these two dates and show me what changed."*

## How it is put together

```
src/
  app/            router plumbing: session guard, error boundary, 404
  components/     brand mark, icon set, UI primitives
  context/        auth, capabilities, workspace state
  features/
    auth/         sign-in screen
    earth/        the 3D globe (three.js) and its generated textures
    launch/       the veil that carries the descent across the route change
    workspace/    shell, top bar, sidebar, navigation model
    query/        composer, upload staging, analysis progress
    results/      result router, contextual variants, advanced disclosure
    raster/       GeoTIFF decode, colour ramps, the raster viewer
    capabilities/ history/ imagery/ exports/ settings/ help/
  services/       the only code that touches the network
  types/api.ts    mirrors backend/app/api/schemas.py exactly
  utils/          formatting and label vocabulary
  styles/         design tokens and base
```

Three rules hold the thing together:

**One network layer.** No component calls `fetch`. `services/satquery.ts` has
one function per endpoint the backend actually publishes; `services/http.ts`
turns the backend's single error envelope into one `ApiError` type.

**The contract is copied, not invented.** `types/api.ts` mirrors the Pydantic
models. Where the backend has not defined a payload yet — detection records,
for instance — the component says so in a comment and degrades, rather than
inventing a shape the backend will have to match later.

**Progressive disclosure.** The default view is the answer. The imagery
metadata, the capability that was selected and why, the resolved parameters and
the per-stage outcome are all present on every result, folded away behind
*Imagery analysed* and *Analysis details*.

## The globe

`features/earth` draws Earth from the Natural Earth 110m coastlines that ship
with the `world-atlas` package, projected onto a canvas and shaded at runtime.
There is no bitmap in the repository and no network request: the globe renders
offline, which matters for a demo. WebGL is feature-detected and falls back to
a flat CSS globe; `prefers-reduced-motion` replaces the descent with a
cross-fade.

## Sessions

**The backend publishes no authentication endpoint.** There is no
`/api/auth/login`, no token issuer and no user model in `backend/app`. Rather
than post credentials to an endpoint that does not exist, `services/auth.ts`
defines an `AuthProvider` interface and ships one honest implementation:
`LocalSessionProvider` opens a workspace session on this device after
confirming the analysis service is reachable, and stores an operator name and
nothing else. A passphrase is never transmitted and never stored.

When the backend grows real authentication, implement `AuthProvider` against
it and swap the `authProvider` export. Nothing else changes — every consumer
goes through `AuthContext`.
