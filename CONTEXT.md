# SatQuery: working context for the next session

> **For the next Claude session.** The user will say "read the context file and
> continue". This file says what the project is, what exists, what was done in
> earlier sessions, what is still open, and the traps to avoid. Last updated
> **2026-10-17**. The automatic-imagery work of that day (section 3a) is in
> commit `80c202e` on `main`, verified live with the user's Groq key. Check
> `git log` first: anything newer happened after this file was written.

---

## 1. The project in one paragraph

SatQuery AI (Smart India Hackathon 2026, problem statement SIH26167) answers
natural-language questions about satellite imagery. A user uploads GeoTIFFs and
asks, for example, "How healthy is the vegetation?", "Find areas affected by
flooding" or "What happened to the forest between these two images?". The system
works out which analysis answers the question, checks deterministically that the
imagery can support it, runs a tool from a controlled registry, and returns an
answer with a map, findings, a confidence breakdown and an execution trace.
Principle: **the model proposes, deterministic code decides.** Backend: FastAPI +
Python. Frontend: React + TypeScript + Vite. The project folder is
`C:\Users\VINAYAK GUPTA\OneDrive\Documents\Satquery` (Windows 11; Bash and
PowerShell both available).

## 2. The architecture diagram the user works from

The user drives the work from a six-box diagram (an image they paste). Every box
is implemented. Where each lives:

| Box | Contents in the diagram | Where it is |
|---|---|---|
| 1. Multimodal query input | single optical, SAR, optical+SAR pair, bi-temporal pair, NL question | `backend/app/api/ingestion.py`, `validator/validator.py` |
| 2. Query understanding (LLM) | intent, location, time, metric, modality detection | `agents/` (rules, Ollama, hosted), `controller/task_understanding/` (`context.py` for place/time/metric/modality) |
| 3. Agentic orchestrator | select tool, sequence steps, route to VLM or deterministic engine, build plan | `controller/` stages, `pipeline.py`; `registry/registry.py` has `Engine` = deterministic / vlm / hybrid |
| 4A. VLM core | fine-tuned VLM (BigEarthNet), VQA, captioning + region grounding, bi-temporal change-VQA, optical+SAR cross-modal | `tools/vlm/` (`vqa.py`, `captioning.py`, `change_vqa.py`, `client.py`, `core.py`); fine-tuning in `finetune/` |
| 4B. Deterministic engines | NDVI/NDWI/NDBI, change detection, AOI and CRS, raster processing | `tools/indices/`, `tools/change/`, `tools/landcover/`, `tools/detection/`, `tools/sar/`, `tools/fusion/`, `tools/raster/` (`aoi.py`, `crs.py`, `render.py`) |
| Data sources | Sentinel-2, Sentinel-1, Landsat, Cartosat-2S / RISAT (eval) | band and sensor handling in `tools/raster/`; RISAT compact-pol (RH/RV) in `tools/sar/backscatter.py` |
| 5. Validation and evidence | benchmark evaluation (VRSBench, RSVQA, CDVQA), confidence scoring, execution trace, map overlay | `app/evaluation/`, `scripts/evaluate_benchmark.py`, `controller/result_integration/confidence.py`, `TraceEvent` in `schemas/results.py` |
| 6. Grounded answer | answer, map, findings, supporting evidence | `controller/result_integration/` (narrators, integrator); frontend `features/results/` |

Tell the user this about box 4A: the fine-tuning notebook trains on **RSVQA-LR**
(Sentinel-2), not BigEarthNet. BigEarthNet is 66 GB, and its VQA edition
(RSVQAxBEN) has about 15 million questions, neither of which fits Kaggle's free
limits. The user has been told this and was advised to relabel the box
"Fine-tuned VLM (RSVQA-LR, Sentinel-2)".

## 3. Current state

- **Code: complete.** Commits `1081837` (the whole architecture) and `18e330e`
  (current Groq models, quota handling).
- **Tests:** 682 backend tests pass on both raster backends (641 before
  2026-10-17, plus 41 in `tests/test_acquisition.py`). The frontend lints and
  builds clean.
- **UI:** verified in headless Chrome at desktop and phone width (Playwright
  driving the installed Chrome, from a scratch virtual environment).
- **Real model runs:** verified with the user's Groq key: NDVI, captioning with
  regions, VQA on one image and on an optical+SAR pair, change-VQA, and fusion.
- **`backend/.env`** holds `SATQUERY_AGENT_API_KEY` (valid, updated by the user
  on 2026-09-27) and `SATQUERY_VQA_ENABLED=true`. **Never print or read the key
  value.** Check it is set with
  `sed -n 's/^\([A-Z_]*\)=\(.\).*/\1 = <set>/p' backend/.env`.

### What the system can do

| Capability | Engine | Tool id |
|---|---|---|
| NDVI / NDWI / NDBI with cloud (SCL/QA) masking | deterministic | `ndvi`, `ndwi`, `ndbi` |
| Land-cover classification (rule-based) | deterministic | `land_cover_classification` |
| Landscape object detection (connected regions) | deterministic | `object_detection` |
| SAR water and flood mapping (dB, speckle, Otsu) | deterministic | `sar_analysis` |
| Optical + SAR water fusion (Cohen's kappa) | deterministic | `optical_sar_fusion` |
| Bi-temporal change (index difference, SAR log-ratio) | deterministic | `change_detection` |
| VQA (one image, or optical+SAR pair) | vlm | `satellite_vqa` |
| Captioning + region grounding | vlm | `image_captioning` |
| Change-VQA (measured first, then described) | hybrid | `change_vqa` |

## 3a. Automatic imagery (added 2026-10-17)

The user asked that nobody should have to upload imagery. Now a request
without files fetches it.

- **Package:** `backend/app/acquisition/`.
  - `location.py`: the location field, then coordinates or a bbox in the
    question, then the first place name, geocoded with Nominatim. It prefers
    area results to points: "Hosur" ranked the railway station first.
  - `planner.py`: the sensor and windows from the task and dates. Flooding
    uses Sentinel-1 unless the question says optical. Change gets before and
    after windows. Fusion gets S2 plus S1 within 12 days.
  - `catalog.py`: Planetary Computer STAC search, SAS token signing, coverage,
    and grouping tiles by pass.
  - `reader.py`: rasterio WarpedVRT reads of remote COGs onto one grid, using
    the overview level.
  - `service.py`: ranking, an SCL cloud check on the leading candidates,
    parallel band download, removing the +1000 offset for baseline >= 04.00,
    and writing a tagged GeoTIFF.
- **Pipeline** (`pipeline.py`): `run(..., acquire=)` is called after
  understanding, and only when the task was understood. The files then go
  through adaptation and validation like uploads.
  - The tool is given `mask_band=SCL` when it accepts one.
  - A failed fetch sets `PipelineRun.acquisition` and becomes the answer.
    Outcome `needs_input` (no place) or `imagery_unavailable` gives status
    `needs_clarification`; `acquisition_failed` gives `execution_error`.
- **API:** `files` is optional and `location` is a new form field.
  - The pipeline runs in a threadpool.
  - `TaskResponse.acquisition` and `capabilities.auto_fetch` are new.
  - With `SATQUERY_FETCH_ENABLED=false`, a request without files gets a 400.
- **Frontend:**
  - The composer allows Analyse with no file when `auto_fetch` is on, and
    shows a location field and place-based suggestions.
  - The progress view has a fetch stage.
  - `AcquisitionPanel` shows the place, scenes and notes. `NonSuccessResult`
    has a "Where should SatQuery look?" branch, and the Help page explains it.
- **Rules reader:** "lost / gained / shrunk / ..." with two dates (or
  "since X") now means change detection. "surface water" and similar phrases
  mean `ndwi`.
- **Measured live** (from this machine, about 0.5-1 MB/s to Planetary
  Computer, which is in West Europe):

  | Question | Time |
  |---|---|
  | Pune NDVI | 17 s |
  | Kochi flood, S1 | 10 s |
  | Hosur change 2019 to 2025, 4-tile mosaic | 45 s |
  | Chilika NDWI | 15 s |
  | Fusion near Kochi | 44 s |

  Time is dominated by bytes, which is why only the needed bands are
  fetched, the defaults are 20 km and 1024 px, and grids snap to 10/20/40/80 m.
- **Tests:** `conftest.py` forces `SATQUERY_FETCH_ENABLED=0`. Acquisition tests
  turn it on and monkeypatch `location.request_json`, `catalog.request_json`
  and `reader.read_asset`.
- **Not done:** no Landsat; no mosaicking of different dates; areas over
  20 km are cut, not tiled.

## 4. How to run things

```bash
# Backend (from backend/)
.venv/Scripts/python.exe -m pytest -q -p no:warnings                                  # 682 tests
SATQUERY_RASTER_BACKEND=builtin .venv/Scripts/python.exe -m pytest -q -p no:warnings  # the same, without GDAL
.venv/Scripts/uvicorn app.main:app --reload                                           # http://127.0.0.1:8000

# Demo data: 5 GeoTIFFs, including a cloudy optical + SAR flood-date pair
.venv/Scripts/python.exe scripts/make_demo_rasters.py demo_data

# Frontend (from frontend/)
npm run dev            # http://localhost:5173 (proxies /api to :8000)
npm run lint && npm run build
```

Tests are hermetic: `backend/conftest.py` stops `.env` being read and removes
`SATQUERY_AGENT_*` and `SATQUERY_VQA_*` from the environment, so the tests
never call Groq.

## 5. Groq: models and free-tier limits (measured 2026-09-27)

- **Defaults** (`backend/app/config/settings.py`): question understanding uses
  `openai/gpt-oss-120b`; vision uses `qwen/qwen3.8-27b`. Groq had retired the
  earlier `llama-3.3-70b-versatile` and `llama-4-scout`. To check which models
  are live, call GET `/openai/v1/models` with the key. Always send a
  `User-Agent` header (see traps).
- **qwen3.8-27b free tier:** 7,000 input tokens per minute and **200,000 per
  day** (a rolling window). Every image costs **about 2,080 tokens whatever its
  size**, because Groq rescales images itself. That allows about 95 one-image
  vision questions a day, or 48 two-image ones. Deterministic tools use no
  tokens.
- When the daily budget runs out, Groq returns 429 with a long `Retry-After`.
  `client.RateLimited` reports that at once with the wait time. The benchmark
  script then stops and writes no report (exit code 3).

## 6. Open items: what to do next

1. **Run the RSVQA-LR benchmark for `qwen/qwen3.8-27b`.** It has not been
   done: on 2026-09-27 the daily quota ran out mid-run. Nothing was written.
   - The RSVQA-LR data (CC-BY-4.0, about 100 MB) was in a session scratchpad,
     which is now gone. Download again from https://zenodo.org/records/6344334:
     `LR_split_test_questions.json`, `LR_split_test_answers.json` and
     `Images_LR.zip` (unzip it). Keep it outside the OneDrive project folder.
   - Run from `backend/`:
     ```bash
     PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/evaluate_benchmark.py rsvqa \
       --questions <dir>/LR_split_test_questions.json --answers <dir>/LR_split_test_answers.json \
       --images <dir>/Images_LR --types presence,comp,rural_urban \
       --sample 500 --seed 0 --limit 90 --delay 18 --name rsvqa_lr
     ```
   - This takes about 30 minutes and uses most of a day's quota; run it in the
     background.
   - `--sample 500 --seed 0` picks the same questions the Kaggle notebook
     measures, and `--limit 90` scores the first 90 of them, so the results
     are comparable.
   - The report goes to `backend/evaluation_reports/` (git-ignored) and to
     `latest.json`. Confidence scoring then reads it automatically: answers
     from `hosted:qwen/qwen3.8-27b` stop being "unrated".
   - The user already approved spending their quota on this.
2. **Wire in the fine-tuned model.** The user was running
   `finetune/finetune_rsvqa.ipynb` on Kaggle (T4, about 1.5–3 hours).
   - The result is `satquery-qwen2vl-rsvqa.zip`, about 70–75 MB. It holds
     `adapter/`, `served_model.json`, `benchmark_report.json` (identity
     `hosted:satquery-qwen2vl-rsvqa`) and `benchmark_report_base.json`.
   - Ask the user for the zip's path, unzip it into `models/` (git-ignored),
     and follow `finetune/README.md`: `serve.py` on port 8001, then
     `SATQUERY_VQA_BASE_URL`, `SATQUERY_VQA_MODEL` and
     `SATQUERY_VQA_BENCHMARK_REPORT` (absolute path) in `.env`.
   - The user's GPU is a GTX 1650 (4 GB), so the model needs `--load-in-4bit`
     (bitsandbytes plus a CUDA build of torch). That path is **untested**.
     The CPU fallback works but is slow.
   - Compare `benchmark_report.json` with `benchmark_report_base.json`, and
     with the Groq run from item 1.
3. **Resolved 2026-10-17.** `.claude/settings.json` (an old permission
   allowlist) was restored rather than deleted; the user said "yes for
   everything" without picking an option.
4. **Skipped at the user's choice:** testing with real Cartosat-2S / RISAT
   products. That needs a Bhoonidhi account, which only the user can create.
5. **Optional:** the RSVQAxBEN (BigEarthNet) scale-up needs a paid GPU budget.

## 7. What was done, and why (so it is not undone)

**Session of 2026-09-26** (reconstructed from the code; no notes were kept):
built the capabilities and the frontend views for boxes 1–6, with most tests.
It left 3 failing tests and several modules untested.

**Session of 2026-09-27**: finished the work, found the bugs below, and fixed
them. Each fix has a test.

- `tool_selection/selector.py`: fusion could never be selected. The selector
  read "images need dates" (`requires_temporal_information`) as "this is a
  before/after comparison". It now excludes `requires_optical_and_sar_pair`.
- `task_understanding.py` CHANGE_PHRASES: added "between these (two)
  images/dates", so "What happened between these two images?" is read as
  change and routes to `change_vqa`.
- The hosted understanding prompt (`agents/providers.py` PROMPT): "counting or
  finding" sent "Is there a river?" to object detection. It now separates
  yes/no questions (`image_analysis`) from count/list requests. The user was
  told this was checked on 11 questions, with 11 correct. Do **not** add
  "only choose a task whose tool is allowed": it made `flood_mapping` return
  null.
- `app/__init__.py` USER_AGENT: Groq's Cloudflare rejects Python's default
  urllib agent with 403 / error 1010. Both hosted clients send
  `SatQuery/<version>`.
- `tools/vlm/client.py`:
  - Waits of 30 seconds or less on 429/503 are retried up to 4 attempts.
  - A longer 429 raises `RateLimited` at once, with the wait in words.
  - 401/403 hints name the key; 5xx says "temporarily unavailable".
- `config/settings.py`: `SATQUERY_VQA_API_KEY` and `resolved_vqa_api_key`.
  The Groq key is only ever sent to Groq's endpoint, never to a self-hosted
  model. A self-hosted `SATQUERY_VQA_BASE_URL` needs no key to be "available".
- `tools/raster/render.py`: partly cloudy scenes rendered almost black,
  because the 2–98% stretch was set by the clouds. SCL cloud, shadow and snow
  classes no longer set the stretch; clouds still draw white.
- `tools/raster/crs.py`: consistent "needs rasterio" error wording. The failing
  tests had wrong coordinate expectations: UTM zone 43, easting 699 960 is
  about 76.9°E.
- Evaluation (`evaluation/runner.py`, `scripts/evaluate_benchmark.py`):
  - `select()` does seeded random sampling; the first N questions of RSVQA
    cover only 5 images.
  - `--types` leaves out RSVQA-LR "count" questions (raw counts like "403"),
    as VLM papers such as GeoChat do.
  - `--limit` scores a subset of the sample; `--delay` paces calls.
  - `BenchmarkInterrupted` stops a run when the quota runs out.
- Frontend:
  - `types/api.ts` now matches the backend contract (`route`, `understood`,
    `findings`, `confidence_report`, `trace`, `engine`, `bounds_lonlat`,
    `vlm_provider`).
  - New parts: `UnderstandingStrip`, `Findings`, `ConfidencePanel`,
    `PreviewPair`, and an execution trace in `AnalysisDetails`.
  - `TextResult` covers captions with outlined regions, change-VQA and
    cross-modal VQA; `ClassesResult` has a fusion branch; engine tags appear
    in the header and on capability cards.
  - `vite.config.ts`: removed the `/results` and `/capabilities` proxies.
    Those are app routes, and proxying them served JSON on reload.
- `finetune/`:
  - `finetune_rsvqa.py` is the source; `build_notebook.py` generates
    `finetune_rsvqa.ipynb` from it.
  - `serve.py` is an OpenAI-compatible server; `README.md` has the steps.
  - The notebook runs end to end on CPU with `SATQUERY_SMOKE_TEST=1` and
    `hf-internal-testing/tiny-random-Qwen2VLForConditionalGeneration`.
  - Label masking was verified: training covers only `answer<|im_end|>`.
  - The pins are `transformers==4.51.3`, `peft==0.15.2`, `accelerate==1.6.0`.
- Docs: `README.md` (capabilities, grounded answers, benchmark, fine-tuning,
  measured free-tier budget), `backend/.env.example`, the tree in
  `System_Architecture.md` §14, and `.gitignore` (evaluation_reports,
  `work/`, `models/`).

## 8. Traps and conventions

- **Line endings.** Many files are CRLF and git has `core.autocrlf=true`.
  - Prefer the Edit tool.
  - A Python `open(..., "w")` rewrite on Windows converts the whole file.
  - Generating strings that contain `\n` through a Bash heredoc into Python
    once wrote real line breaks into a string literal; check with
    `ast.parse`.
  - For scripted edits, read and write bytes and preserve the file's own
    endings.
- **Windows console:** set `PYTHONIOENCODING=utf-8` when printing model
  output.
- **Background jobs:** foreground waits over 10 minutes time out; run long
  jobs in the background. To stop one, use PowerShell
  `Get-CimInstance Win32_Process` filtered on the command line, then
  `Stop-Process`.
- **Secrets:** never print `.env` values; send keys only in headers. No test
  may reach the network (monkeypatch `client.post_json` or
  `urllib.request.urlopen`).
- **Vision screens without a working key:** a stub backend replaces
  `app.tools.vlm.client.post_json` with canned replies. That is how the UI was
  checked; keep such stubs in a scratch folder, never in the repo.
- **The user:**
  - Commits go **directly to main**; the user chose this.
  - End commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - The user wants to be told plainly what is needed from their side, and
    asks "is everything complete?", so report gaps honestly.
  - The user's persistent memory note is in
    `~/.claude/projects/c--Users-VINAYAK-GUPTA-OneDrive-Documents-Satquery/memory/`.
