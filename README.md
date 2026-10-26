# SatQuery AI

**Natural language in. Validated remote-sensing workflows out.**

Ask a question about a place in plain English — *"How healthy is the
vegetation in Pune?"*, *"Find the areas affected by flooding near Kochi in
August 2024"*, *"Has vegetation been lost around Hosur between 2019 and
2025?"* — and SatQuery finds the place, fetches the right Sentinel-2 or
Sentinel-1 imagery for it, works out which analysis answers the question,
checks that the imagery can actually support that analysis, runs it, and
returns a map, statistics and an explanation of every decision it made. You can
also attach your own GeoTIFFs instead.

The model proposes; deterministic code decides. A language model may interpret
the question, but only tools in a controlled registry can run, and a
deterministic validator checks every input before anything executes. A
reasoning error becomes a precise refusal, never a confident wrong map.

Built for Smart India Hackathon 2026 (problem statement SIH26167).

## What it can do

| Capability | Ask something like | Imagery | How it works |
|---|---|---|---|
| Vegetation, water, built-up indices | "How healthy is the vegetation?" | optical, 1 scene | NDVI, NDWI, NDBI with nodata, scale/offset and cloud (SCL/QA) masking |
| Land-cover classification | "Classify the land cover" | optical, 1 scene | Transparent NDWI/NDVI/NDBI decision rules: water, dense and sparse vegetation, built-up, bare soil |
| Landscape object detection | "How many water bodies are there?" | optical, 1 scene | Connected regions of one land-cover class, with area, bounding box and centroid |
| SAR water and flood mapping | "Find areas affected by flooding" | SAR (VV/VH): 1 scene, or a dry-season reference + flood-period scene | Calibrated backscatter in dB, speckle filter, fixed or Otsu threshold. With a reference, flooding is *new* water: rivers, lakes and sea are reported separately and not counted |
| Optical + SAR water fusion | "Find areas affected by flooding" | 1 optical + 1 SAR, ≤12 days apart | NDWI where the sky is clear, radar backscatter under cloud; every pixel labelled by which sensor saw water, with Cohen's kappa for their agreement |
| Change detection | "Show where vegetation decreased between these dates" | 2 co-registered scenes | Index differencing for optical pairs (the index follows the question); dB log-ratio for radar pairs |
| Visual question answering | "Is there a river in this image?" | optical, SAR, or an optical + SAR pair | A vision-language model reads a rendered preview. **Off unless you enable it** |
| Captioning with region grounding | "Describe this image" | optical or SAR | The model describes the scene and outlines what it names; each box is placed back on the map. **Off unless you enable it** |
| Change-VQA | "What happened to the forest between these two images?" | 2 dates | Change is measured deterministically first, then the model answers with both dates and those numbers in hand. **Off unless you enable it** |

The first six are deterministic, run offline and cost nothing. The last
three are the vision-language model core, which an operator switches on.
Every answer says which engine produced it — deterministic, model, or
measured-then-described — because those deserve different degrees of trust.
Ask for something the imagery cannot support — an NDVI on a radar scene, cars
in 10 m pixels — and SatQuery says why instead of guessing.

## Quick start

**With Docker** (nothing else to install):

```bash
docker compose up --build         # then open http://localhost:8080
```

It reads `backend/.env` when there is one. CI builds both images on every
push, starts the stack and checks that nginx serves the app and the API.

**Publicly, on Render (free).** The root `Dockerfile` is a single image that
serves the workspace and the API on one port (`$PORT`, 7860 by default), and
`render.yaml` describes it as a free web service:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/VinayakGupta-1/SatQuery-AI)

Sign in with GitHub, paste the Groq key when asked for
`SATQUERY_AGENT_API_KEY` (or leave it empty for the offline rules), and
Render builds the image and redeploys on every push to `main`. The public
demo runs without sign-in, and visitors share the key's free-tier quota; the
deterministic tools cost nothing. A free service sleeps after 15 minutes
without visitors and takes about a minute to wake.

`deploy/huggingface/deploy.py` publishes the same image to a Hugging Face
Space instead, but Docker Spaces now need a PRO subscription.

**Without Docker** you need Python and Node.js (tested on Python 3.13 and Node 24; Vite needs
Node 20.19 or newer).

```bash
# 1. The analysis service
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-lock.txt   # exact, tested versions (requirements.txt has the ranges)
uvicorn app.main:app --reload     # http://127.0.0.1:8000, docs at /docs

# 2. The workspace, in a second terminal
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

### No imagery needed

Ask about a place and attach nothing. SatQuery fetches the imagery itself:

| Ask | What is fetched |
|---|---|
| "How healthy is the vegetation in Pune?" | The clearest Sentinel-2 L2A scene of the last 120 days |
| "Map the surface water around Chilika Lake in March 2024" | The clearest Sentinel-2 scene from March 2024 |
| "Find the areas affected by flooding near Kochi in August 2024" | Two Sentinel-1 RTC radar scenes on the same orbit track: August 2024, and the January-April dry season as reference. Radar sees through monsoon cloud; the reference keeps the sea and backwaters from counting as flood (Kochi: 0.9% flooded, 48.2% permanent water) |
| "Has vegetation been lost around Hosur between 2019 and 2025?" | One scene from each year, the 2019 one matched to the season of the 2025 one, on one pixel grid |
| "Fuse optical and SAR to map water near 9.97, 76.28" | A Sentinel-2 scene and the nearest Sentinel-1 pass within 12 days |

How it works (`backend/app/acquisition/`):

1. **Where.** The place is taken from the location field, from coordinates in
   the question, or from the first place name in it, looked up in
   OpenStreetMap's Nominatim. Areas up to 20 km across are fetched. A larger
   place is cut to 20 km around its centre, and the answer says so.
2. **What and when.** The understood task decides the sensor and the number of
   scenes. The question's dates decide the search windows.
3. **Which scene.** Scenes are searched in Microsoft Planetary Computer's free
   STAC catalogue (no account needed). They are ranked by coverage of the
   area, then cloud, then recency. The catalogue's cloud figure describes a
   whole 110 km tile, so the leading candidates are re-checked on their own
   SCL band over the area itself. Adjacent tiles of one pass are mosaicked.
4. **Download.** Only the area's pixels are read from the cloud-optimised
   GeoTIFFs, and only the bands the task uses. Large areas are read from the
   files' 20/40/80 m overviews. A typical question takes 10–45 s, most of it
   download.
5. **Harmonise and write.** The +1000 reflectance offset of Sentinel-2
   processing baseline 04.00 and later is removed. Each scene is written as a
   self-describing GeoTIFF, which is then validated exactly like an upload.
   For tools that can mask cloud, the scene's SCL band is named as the cloud
   mask, as a visible resolved parameter.

Every result shows the resolved place, each scene's date, platform and cloud
over the area, the catalogue item ids, and every adjustment made. If no place
is named, or the archive has nothing usable, the answer says exactly that and
what to change.

### Something to analyse

A generator writes five synthetic but genuine GeoTIFFs over one footprint: two
Sentinel-2-style optical scenes ten months apart (a forest block is cleared and
a reservoir shrinks between them), two Sentinel-1-style radar scenes before
and during a monsoon flood, and an optical scene on the flood date, partly
under cloud, with its Scene Classification Layer.

```bash
cd backend
python scripts/make_demo_rasters.py demo_data
```

| Upload | Ask |
|---|---|
| `scene_2024-09-18.tif` | "How healthy is the vegetation in this scene?" |
| `scene_2024-09-18.tif` | "Classify the land cover in this image." |
| `scene_2024-09-18.tif` | "How many water bodies are there?" |
| `scene_2023-11-04.tif` + `scene_2024-09-18.tif` | "Compare these two dates and show me what changed." |
| `sar_2024-08-22.tif` | "Find areas affected by flooding." |
| both `sar_*.tif` | "Compare these two radar images and show where flooding appeared." |
| `scene_2024-08-22_cloudy.tif` + `sar_2024-08-22.tif` | "Find areas affected by flooding." |

Real imagery works the same way: Sentinel-2 from the
[Copernicus Browser](https://browser.dataspace.copernicus.eu), Landsat from
[EarthExplorer](https://earthexplorer.usgs.gov), or ISRO products from
[Bhoonidhi](https://bhoonidhi.nrsc.gov.in).

## Configuration

Nothing is required. Copy `backend/.env.example` to `backend/.env` to change
anything:

- **`SATQUERY_AGENT_API_KEY`**: a free [Groq](https://console.groq.com/keys)
  key lets a hosted model interpret questions. Without one, an offline keyword
  engine does it. Only the question's text is sent.
- **`SATQUERY_VQA_ENABLED=true`**: switches on the vision-language model core
  (VQA, captioning, change-VQA). With the default hosted provider this sends a
  rendered preview of the image to the vision model, which is why it is a
  separate decision from the key. `SATQUERY_VQA_PROVIDER=ollama` runs a vision
  model on your own machine instead, and `SATQUERY_VQA_MODEL` swaps in any
  vision model — including one fine-tuned on remote-sensing data — without a
  code change.
- **`SATQUERY_SUPABASE_URL`** and **`SATQUERY_SUPABASE_PUBLISHABLE_KEY`**:
  accounts. People sign up with a name, email and password, confirm the
  address from the email Supabase sends, and sign in; every analysis request
  then carries their access token, which the backend verifies against the
  project's published keys, and each person's results are kept in the
  project's `analyses` table, readable only by them (row level security).
  Without these two values the API is open and the workspace opens local
  sessions. Both values are public by design. In the Supabase dashboard set
  **Authentication -> URL Configuration -> Site URL** to where the workspace
  runs (`http://localhost:5173`, or `http://localhost:8080` with Docker) and
  add `<that URL>/login` under Redirect URLs, so verification and
  password-reset links come back to the app. Supabase's built-in email
  service only delivers to members of your Supabase organisation; configure
  custom SMTP (Authentication -> Emails) before inviting anyone else.
- **`SATQUERY_FETCH_ENABLED=false`**: turns automatic imagery off, for a
  server that must not reach the internet; uploads are then required. With it
  on (the default), the place named in a question goes to OpenStreetMap's
  geocoder and the area and dates to Planetary Computer's catalogue.
  `SATQUERY_FETCH_MAX_EXTENT_KM` (20) and `SATQUERY_FETCH_MAX_PIXELS` (1024)
  trade area and detail against download time.

`frontend/.env.example` covers pointing the workspace at a backend on another
origin.

### Measuring the vision model

A model's answer is only as trustworthy as the model, so SatQuery does not
invent a confidence for one. Until a model has been benchmarked, its answers
are shown as **unrated**. Download a remote-sensing VQA benchmark and measure
it:

```bash
cd backend
# RSVQA-LR, about 100 MB: https://zenodo.org/records/6344334
python scripts/evaluate_benchmark.py rsvqa     --questions RSVQA_LR/LR_split_test_questions.json     --answers   RSVQA_LR/LR_split_test_answers.json     --images    RSVQA_LR/Images_LR     --types presence,comp,rural_urban --sample 500 --limit 90 --delay 18
```

`--sample` scores a seeded random sample spread over the benchmark (its file
lists questions image by image, so "the first 500" is five scenes); `--limit`
scores the first N of that sample, a subset of exactly the questions the
fine-tuning notebook measures. `--types` leaves out RSVQA-LR's count
questions, whose answers are raw object counts no model can read from 10 m
pixels.

`--delay` paces the calls to the endpoint's limit. On Groq's free tier
(measured September 2026 with `qwen/qwen3.8-27b`) every image costs about
2,080 input tokens whatever its size, against 7,000 tokens a minute and
200,000 a day: a question every 18 seconds, and about 95 image questions a
day, shared with the app. In practice the limit can bite sooner: on
17 October 2026 a run stopped after 60 questions. If the budget runs out
mid-run the script stops and writes no report, rather than scoring the
unanswered questions as wrong. Every answer is saved as it arrives
(`evaluation_reports/<name>_answers.jsonl`), so running the same command again
once the quota has reset asks only the remaining questions; `--fresh` starts
over.

The same budget applies inside SatQuery: about 95 one-image vision questions
a day, or 48 two-image ones (change-VQA, optical + SAR). Deterministic
analyses use no tokens. A short rate limit is waited out; an exhausted daily
budget is reported at once with how long until it frees up.

VRSBench and CDVQA exports are read with the `records` subcommand (see the
script's docstring). The report lands in `backend/evaluation_reports/`, and
from then on that model's answers carry its measured accuracy as a confidence
factor.

### Fine-tuning a remote-sensing model

[finetune/](finetune/README.md) holds a Kaggle notebook that fine-tunes
Qwen2-VL-2B on RSVQA-LR with LoRA on a free GPU, measures it before and after
on the same questions as the script above, and a small server that exposes the
result to SatQuery as an OpenAI-compatible endpoint. Pointing
`SATQUERY_VQA_BASE_URL` at it swaps the model in, with its measured accuracy.

Measured on Kaggle (T4, 24 October 2026), on the same 500 RSVQA-LR test
questions:

| Question type | Qwen2-VL-2B, base | Fine-tuned (LoRA, 1 epoch) |
|---|---|---|
| Presence ("Is there a river?") | 47.3 % | **94.0 %** |
| Comparison ("Are there more roads than buildings?") | 65.9 % | **88.1 %** |
| Rural or urban | 66.7 % | **83.3 %** |
| **Overall** | **58.4 %** | **90.4 %** |

## How it works

Every request passes through ten stages: understand the question, classify the
task, plan it, derive input requirements, select a tool from the registry,
**validate the imagery deterministically**, resolve parameters, authorise
execution, run the tool, and integrate the result into one response with a full
audit trail. `POST /analyze/validate` runs the same stages and stops before
the tool, so a user learns their upload is unsuitable without waiting for a
computation.

Every answer comes back grounded:

- **Read as** — the intent, place, period, measure and sensor the question was
  understood to name.
- **Findings** — the answer broken into checkable parts: what, how much, and
  where, as a compass sector and longitude/latitude.
- **Confidence** — the weakest of the measured factors (how clearly the
  question mapped to a capability, how much of the scene could be observed,
  how well two sensors agree, a model's benchmark accuracy), with the reason.
  It is a reliability indicator, not a calibrated probability.
- **Execution trace** — every stage as it ran, timed, with the tool's own steps.

- [frontend/README.md](frontend/README.md) — the workspace's structure and conventions

## Tests

```bash
cd backend
python -m pytest                                   # 777 tests
SATQUERY_RASTER_BACKEND=builtin python -m pytest   # same suite, no GDAL
# PowerShell: $env:SATQUERY_RASTER_BACKEND="builtin"; python -m pytest
```

The suite runs twice: once with rasterio/GDAL and once on the dependency-free
GeoTIFF codec, to prove the two raster backends agree. It never reads
`backend/.env`, never calls a hosted model and never fetches imagery: the
acquisition tests replace the catalogue, geocoder and remote reader with fakes.

```bash
cd frontend
npm test                          # Vitest: formatting, suggestions, request bodies
npm run lint && npm run build     # ESLint, then tsc -b and the production build
```

GitHub Actions (`.github/workflows/ci.yml`) runs both backend suites, the
frontend tests, lint and build, and a Docker build-and-serve check on every
push and pull request.

Questions can be asked in Hindi as well as English; month names, places and
the analysis are read from the Hindi text even without a hosted model.

Dates are always read by deterministic code, never by a model
(`backend/app/controller/task_understanding/context.py`): days
(`2024-08-15`, `15/08/2024` day first, `August 15, 2024`), months
(`Aug 2024`, `2024-08`, Hindi month names), years, ranges (`between ... and
...`, `since 2020`, `before 2019`), Indian seasons (`monsoon 2024`,
`kharif 2023`, `rabi 2023` = November 2023 to April 2024, `last monsoon`) and
relative periods (`last month`, `past 90 days`, `this year`, `पिछले साल`).
Fetched imagery reaches back to 2017 (Sentinel-2) and October 2014
(Sentinel-1); uploads can be of any date their files record.

## Layout

```
backend/
  app/
    agents/       query understanding: rule engine, Ollama or hosted model, and the guard
    controller/   the pipeline stages, from understanding to result integration
    validator/    deterministic input validation
    registry/     the controlled catalogue of tools
    tools/        indices, landcover, detection, sar, change, fusion,
                  vlm (VQA, captioning, change-VQA), raster I/O, AOI and CRS
    evaluation/   benchmark loading and scoring for the vision model
    acquisition/  automatic imagery: geocoding, STAC search, scene choice, download
    auth/         Supabase access-token verification
    storage/      uploads and outputs, with retention
    api/          FastAPI routes, uploads, response shaping, history, progress
  scripts/        demo data generator, benchmark evaluation
  tests/
frontend/         React + TypeScript workspace
finetune/         Kaggle notebook to fine-tune the vision model, and its server
presentation/     SatQuery.pptx, the project presentation
deploy/           Hugging Face Space: its README and the deploy script (needs PRO)
render.yaml       Render blueprint: the free public deployment
Dockerfile        single-container image (workspace + API on one port)
```
