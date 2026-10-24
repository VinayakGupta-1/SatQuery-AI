# Fine-tuning the vision-language model

SatQuery's vision-language model core (VQA, captioning, change-VQA) calls any
OpenAI-compatible endpoint. This folder turns a general vision model into a
remote-sensing one and plugs it back in:

| File | What it is |
|---|---|
| `finetune_rsvqa.ipynb` | The Kaggle notebook: LoRA fine-tuning of Qwen2-VL-2B-Instruct on RSVQA-LR, measured before and after |
| `finetune_rsvqa.py` | Its source. `python build_notebook.py` regenerates the notebook from it |
| `serve.py` | Serves the result as an OpenAI-compatible endpoint SatQuery can call |
| `requirements-serve.txt` | What `serve.py` needs |

## What gets trained, and on what

- **Model:** [Qwen2-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct),
  small enough to fine-tune on a free Kaggle GPU and to serve on a modest one.
- **Data:** [RSVQA-LR](https://zenodo.org/records/6344334) (Lobry et al., 2020,
  CC-BY-4.0): 256x256 Sentinel-2 tiles with presence, comparison and
  rural/urban questions. 16,000 training questions, one epoch.
- **Method:** LoRA (rank 16) on the language model's projections; the vision
  encoder is unchanged. The loss is on the answer only.
- **Measurement:** the base and the fine-tuned model answer the same 500 test
  questions that SatQuery's `scripts/evaluate_benchmark.py --sample 500
  --seed 0 --types presence,comp,rural_urban` uses, scored with SatQuery's own
  scoring code. So the two reports can be compared with each other and with
  any hosted model measured by that script.

**Why not BigEarthNet itself?** BigEarthNet is a 66 GB land-cover
*classification* archive, and its VQA edition (RSVQAxBEN) has about 15 million
questions. Neither fits in Kaggle's free disk and session limits. RSVQA-LR
uses the same Sentinel-2 imagery and is the benchmark SatQuery reports.
Scaling to RSVQAxBEN needs a paid GPU budget, not different code in SatQuery.

## 1. Train on Kaggle (free)

1. Sign in at [kaggle.com](https://www.kaggle.com). Verify your phone number
   (Settings -> Phone verification), because Kaggle allows GPUs and internet
   access only for verified accounts.
2. **Create -> New Notebook**, then **File -> Import Notebook**, and upload
   `finetune_rsvqa.ipynb`.
3. In the right-hand panel: **Accelerator -> GPU T4 x2** (or P100) and
   **Internet -> On**.
4. **Run All**. It downloads RSVQA-LR (about 100 MB), measures the base model,
   trains, and measures again. Expect about two hours; a Kaggle session allows
   twelve.
5. When it finishes, open **Output** and download `satquery-qwen2vl-rsvqa.zip`.
   It holds:
   - `adapter/`: the LoRA weights (tens of MB; the base model is downloaded
     from Hugging Face when served);
   - `served_model.json`: which base model the adapter belongs to;
   - `benchmark_report.json`: the fine-tuned model's accuracy, recorded under
     `hosted:satquery-qwen2vl-rsvqa`;
   - `benchmark_report_base.json`: the base model's accuracy on the same questions.

## Results

The run of 24 October 2026 (Kaggle, one T4, 1,000 steps, about 55 minutes of
training), on the 500 test questions described above:

| Question type | Base | Fine-tuned |
|---|---|---|
| presence | 47.3 % | 94.0 % |
| comp | 65.9 % | 88.1 % |
| rural_urban | 66.7 % | 83.3 % |
| **overall** | **58.4 %** | **90.4 %** |

The training loss fell from 0.26 to about 0.07. Both reports ship in the zip
(`benchmark_report.json`, `benchmark_report_base.json`).

## 2. Serve it

Unzip it into `models/` at the repository root (git ignores that folder), then:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121   # a GPU build; see pytorch.org
pip install -r finetune/requirements-serve.txt
python finetune/serve.py --model-dir models/satquery-qwen2vl-rsvqa --port 8001
```

The model needs about 5 GB of GPU memory in float16. On a 4 GB card such as a
GTX 1650, add `--load-in-4bit` (and `pip install bitsandbytes`). Without a GPU
it runs on the CPU: correct, but several seconds per answer.

## 3. Point SatQuery at it

In `backend/.env`:

```bash
SATQUERY_VQA_ENABLED=true
SATQUERY_VQA_PROVIDER=hosted
SATQUERY_VQA_BASE_URL=http://127.0.0.1:8001/v1
SATQUERY_VQA_MODEL=satquery-qwen2vl-rsvqa
SATQUERY_VQA_BENCHMARK_REPORT=C:/path/to/Satquery/models/satquery-qwen2vl-rsvqa/benchmark_report.json
```

Use the absolute path of the unzipped report: a relative one is read
relative to wherever the backend was started.

Restart the backend. Vision answers now come from the fine-tuned model, and
their confidence carries its measured RSVQA accuracy instead of "unrated". A
Groq key in `SATQUERY_AGENT_API_KEY` keeps working for question understanding
and is never sent to this endpoint.

## What has been verified, and what has not

With `SATQUERY_SMOKE_TEST=1` the whole notebook runs on a CPU in about a
minute, using a tiny random-weight model of the same architecture. That run
exercised every stage: the RSVQA download, sampling, base evaluation, LoRA
training steps with the loss on the answer alone, re-evaluation and packaging.
`serve.py` then served the package, and SatQuery's benchmark script and its
VQA pipeline both got answers from it, with the measured accuracy reaching
confidence scoring. What that run cannot tell you is how accurate the real
model will be: that is what the Kaggle run measures.

**4-bit on a GTX 1650 (4 GB), verified 24 October 2026** on Windows 11 with
Python 3.12, `torch 2.14.1+cu126`, `bitsandbytes 0.50.2` and the pins above,
in a virtual environment outside the OneDrive folder:

- The model loads in about 35 seconds and uses 2.8 GB of GPU memory, 3.2 GB
  while answering on a 1024-pixel SatQuery preview.
- `scripts/evaluate_benchmark.py` against it scored **89.0 %** on the first
  100 of the 500 questions (comparison 87.5 %, presence 91.7 %), in line
  with the 90.4 % measured in float16 on Kaggle: 4-bit costs little.
- Through SatQuery, place questions ("Is there a river near Varanasi?")
  fetched imagery and were answered by this model in about 50 seconds, with
  the confidence citing its measured accuracy instead of "unrated".

```powershell
py -3.12 -m venv $HOME\.satquery-serve
$HOME\.satquery-serve\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cu126
$HOME\.satquery-serve\Scripts\python -m pip install -r finetune\requirements-serve.txt bitsandbytes
$HOME\.satquery-serve\Scripts\python finetune\serve.py --model-dir models\satquery-qwen2vl-rsvqa --load-in-4bit
```
