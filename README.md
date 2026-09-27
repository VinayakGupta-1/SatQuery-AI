# SatQuery AI

**Natural language in. Validated remote-sensing workflows out.**

Ask a question about satellite imagery in plain English — *"How healthy is the
vegetation?"*, *"How many water bodies are there?"*, *"Where did the flood
spread?"* — and SatQuery works out which analysis answers it, checks that your
imagery can actually support that analysis, runs it, and returns a map,
statistics and an explanation of every decision it made.

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
| SAR water and flood mapping | "Find areas affected by flooding" | SAR (VV/VH), 1 scene | Calibrated backscatter in dB, speckle filter, fixed or Otsu threshold |
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

You need Python and Node.js (tested on Python 3.13 and Node 24; Vite needs
Node 20.19 or newer).

```bash
# 1. The analysis service
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload     # http://127.0.0.1:8000, docs at /docs

# 2. The workspace, in a second terminal
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

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
python scripts/evaluate_benchmark.py rsvqa     --questions RSVQA_LR/LR_split_test_questions.json     --answers   RSVQA_LR/LR_split_test_answers.json     --images    RSVQA_LR/Images_LR     --types presence,comp,rural_urban --sample 500 --delay 2.2
```

`--sample` scores a seeded random sample spread over the benchmark (its file
lists questions image by image, so "the first 500" is five scenes). `--types`
leaves out RSVQA-LR's count questions, whose answers are raw object counts no
model can read from 10 m pixels. `--delay` keeps a free tier's rate limit.

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

- [System_Architecture.md](System_Architecture.md) — the design and the reasons for it
- [System_diagram.md](System_diagram.md) — the layers at a glance
- [frontend/README.md](frontend/README.md) — the workspace's structure and conventions

## Tests

```bash
cd backend
python -m pytest                                   # 633 tests
SATQUERY_RASTER_BACKEND=builtin python -m pytest   # same suite, no GDAL
# PowerShell: $env:SATQUERY_RASTER_BACKEND="builtin"; python -m pytest
```

The suite runs twice: once with rasterio/GDAL and once on the dependency-free
GeoTIFF codec, to prove the two raster backends agree. It never reads
`backend/.env` and never calls a hosted model.

```bash
cd frontend
npm run lint && npm run build
```

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
    api/          FastAPI routes, uploads, response shaping
  scripts/        demo data generator, benchmark evaluation
  tests/
frontend/         React + TypeScript workspace
finetune/         Kaggle notebook to fine-tune the vision model, and its server
presentation/     SIH deck and the scripts that build it
```
