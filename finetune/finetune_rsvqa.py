# %% [markdown]
# # SatQuery: fine-tune a vision-language model for remote-sensing VQA
#
# This notebook fine-tunes **Qwen2-VL-2B-Instruct** with LoRA on
# **RSVQA-LR** (Lobry et al., 2020; Sentinel-2 tiles, CC-BY-4.0), measures
# the base and the fine-tuned model on the *same* 500 test questions that
# SatQuery's own `scripts/evaluate_benchmark.py` uses, and packages the
# result so SatQuery can serve it and report its measured accuracy.
#
# **On Kaggle:** Settings -> Accelerator -> *GPU T4 x2* or *GPU P100*;
# Settings -> Internet -> *On*. Then *Run All*. It takes about two hours.
# When it finishes, download `satquery-qwen2vl-rsvqa.zip` from the Output
# panel and follow `finetune/README.md` in the SatQuery repository.
#
# This file is the source of `finetune_rsvqa.ipynb`
# (`python finetune/build_notebook.py` regenerates it). With
# `SATQUERY_SMOKE_TEST=1` it runs end to end on a CPU in a few minutes with a
# tiny random-weight model of the same architecture -- that checks the code,
# not the accuracy.

# %%
import os

# One GPU: the model fits on one, and two would make the Trainer wrap it in
# DataParallel, which LoRA with gradient checkpointing does not need.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

import json
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone

SMOKE_TEST = os.environ.get("SATQUERY_SMOKE_TEST") == "1"
ON_KAGGLE = os.path.isdir("/kaggle/working")

if ON_KAGGLE:
    # Pinned: the versions this notebook was tested against.
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-q",
        "transformers==4.51.3", "peft==0.15.2", "accelerate==1.6.0",
    ])

# %% [markdown]
# ## Settings

# %%
BASE_MODEL = (
    "hf-internal-testing/tiny-random-Qwen2VLForConditionalGeneration"
    if SMOKE_TEST else "Qwen/Qwen2-VL-2B-Instruct"
)
#: The name the model is served under; SatQuery's SATQUERY_VQA_MODEL.
SERVED_NAME = "satquery-qwen2vl-rsvqa"

WORK = "/kaggle/working" if ON_KAGGLE else os.environ.get("SATQUERY_WORK", "work")
DATA = os.environ.get("SATQUERY_RSVQA_DIR", os.path.join(WORK, "RSVQA_LR"))
OUTPUT = os.path.join(WORK, SERVED_NAME)

#: RSVQA-LR's "count" answers are raw object counts ("403 roads") that no
#: model can read from 10 m pixels; VLM evaluations report the other three.
TYPES = {"presence", "comp", "rural_urban"}
TRAIN_SIZE = 32 if SMOKE_TEST else 16000
EVAL_SIZE = 8 if SMOKE_TEST else 500
#: The same seed and sampling as SatQuery's evaluate_benchmark.py --sample,
#: so both measure the model on the same questions.
SEED = 0

BATCH_SIZE, GRAD_ACCUM = (2, 1) if SMOKE_TEST else (4, 4)
LEARNING_RATE = 1e-4
EPOCHS = 1
MAX_STEPS = 2 if SMOKE_TEST else -1

os.makedirs(DATA, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)
print(f"base model {BASE_MODEL}; data {DATA}; output {OUTPUT}; smoke test {SMOKE_TEST}")

# %% [markdown]
# ## RSVQA-LR
#
# About 100 MB from Zenodo record 6344334.

# %%
ZENODO = "https://zenodo.org/records/6344334/files/{}?download=1"
FILES = [
    "LR_split_train_questions.json", "LR_split_train_answers.json",
    "LR_split_test_questions.json", "LR_split_test_answers.json", "Images_LR.zip",
]

for name in FILES:
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        print("downloading", name)
        urllib.request.urlretrieve(ZENODO.format(name), path)
if not os.path.isdir(os.path.join(DATA, "Images_LR")):
    with zipfile.ZipFile(os.path.join(DATA, "Images_LR.zip")) as archive:
        archive.extractall(DATA)


def load_split(split):
    """One RSVQA split, read exactly as SatQuery's load_rsvqa reads it."""
    with open(os.path.join(DATA, f"LR_split_{split}_questions.json"), encoding="utf-8") as handle:
        questions = json.load(handle)["questions"]
    with open(os.path.join(DATA, f"LR_split_{split}_answers.json"), encoding="utf-8") as handle:
        answers = {
            entry.get("id"): entry.get("answer")
            for entry in json.load(handle)["answers"]
            if isinstance(entry, dict) and entry.get("active", True)
        }
    samples = []
    for entry in questions:
        if not isinstance(entry, dict) or not entry.get("active", True):
            continue
        ids = entry["answers_ids"] if isinstance(entry["answers_ids"], list) else [entry["answers_ids"]]
        answer = next((answers[i] for i in ids if answers.get(i) is not None), None)
        if answer is None:
            continue
        samples.append({
            "id": str(entry["id"]),
            "image": os.path.join(DATA, "Images_LR", f"{entry['img_id']}.tif"),
            "question": str(entry["question"]),
            "answer": str(answer),
            "type": str(entry.get("type", "all")),
        })
    return samples


def select(samples, size, seed, types):
    """Identical to app.evaluation.runner.select: a seeded random sample."""
    pool = [sample for sample in samples if sample["type"] in types]
    return random.Random(seed).sample(pool, size) if size < len(pool) else pool


train_set = select(load_split("train"), TRAIN_SIZE, SEED, TYPES)
eval_set = select(load_split("test"), EVAL_SIZE, SEED, TYPES)
print("train", len(train_set), Counter(s["type"] for s in train_set))
print("eval ", len(eval_set), Counter(s["type"] for s in eval_set))

# %% [markdown]
# ## Scoring
#
# Copied from SatQuery's `backend/app/evaluation/metrics.py`, so an accuracy
# measured here means exactly what it means inside SatQuery.

# %%
NUMBER_WORDS = {
    "zero": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
_ARTICLE = re.compile(r"^(a|an|the)\s+")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def normalise(text):
    text = str(text).strip().lower()
    text = re.sub(r"^[\W_]+|[\W_]+$", "", text)
    return _ARTICLE.sub("", text).strip()


def _first_number(text):
    match = _NUMBER.search(text)
    if match:
        return float(match.group(0))
    for word in re.findall(r"[a-z]+", text):
        if word in NUMBER_WORDS:
            return float(NUMBER_WORDS[word])
    return None


def answers_match(answer, reference):
    got, want = normalise(answer), normalise(reference)
    if not got:
        return False
    if want in {"yes", "no"}:
        first = re.findall(r"[a-z]+", got)
        return bool(first) and first[0] == want
    if _NUMBER.fullmatch(want):
        number = _first_number(got)
        return number is not None and number == float(want)
    return got == want


def token_f1(answer, reference):
    got, want = normalise(answer).split(), normalise(reference).split()
    if not got or not want:
        return float(got == want)
    common = sum((Counter(got) & Counter(want)).values())
    if common == 0:
        return 0.0
    precision, recall = common / len(got), common / len(want)
    return 2 * precision * recall / (precision + recall)


def summarise(outcomes):
    per_type = {}
    for kind, correct, f1 in outcomes:
        per_type.setdefault(kind, []).append((correct, f1))
    total = sum(len(values) for values in per_type.values())
    correct = sum(ok for values in per_type.values() for ok, _ in values)
    breakdown = {
        kind: {
            "samples": len(values),
            "accuracy": sum(ok for ok, _ in values) / len(values),
            "token_f1": sum(f1 for _, f1 in values) / len(values),
        }
        for kind, values in sorted(per_type.items())
    }
    return {
        "samples": total,
        "overall_accuracy": correct / total if total else 0.0,
        "average_accuracy": (
            sum(entry["accuracy"] for entry in breakdown.values()) / len(breakdown) if breakdown else 0.0
        ),
        "mean_token_f1": (
            sum(f1 for values in per_type.values() for _, f1 in values) / total if total else 0.0
        ),
        "per_type": breakdown,
    }


# %% [markdown]
# ## Model and prompts
#
# The prompt is SatQuery's benchmark prompt, word for word: the model is
# trained on the form it is measured with.

# %%
import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

CUDA = torch.cuda.is_available()
DTYPE = torch.float16 if CUDA else torch.float32

SHORT_ANSWER_PROMPT = (
    "You are answering a question about {what}. Reply with a single word or "
    "number and nothing else -- for example: yes, no, 3, urban.\n\nQuestion: {question}"
)

processor = AutoProcessor.from_pretrained(BASE_MODEL)
model = Qwen2VLForConditionalGeneration.from_pretrained(
    BASE_MODEL, torch_dtype=DTYPE, device_map={"": 0} if CUDA else None
)


def load_image(path):
    return Image.open(path).convert("RGB")


def conversation(sample, with_answer):
    messages = [{
        "role": "user",
        "content": [
            {"type": "image"},
            {"type": "text", "text": SHORT_ANSWER_PROMPT.format(what="a satellite image", question=sample["question"])},
        ],
    }]
    if with_answer:
        messages.append({"role": "assistant", "content": [{"type": "text", "text": sample["answer"]}]})
    return messages


@torch.no_grad()
def answer_all(samples, batch_size=8):
    """Greedy short answers for ``samples``, the way the benchmark asks."""
    model.eval()
    processor.tokenizer.padding_side = "left"
    answers = []
    for start in range(0, len(samples), batch_size):
        chunk = samples[start:start + batch_size]
        prompts = [
            processor.apply_chat_template(conversation(s, False), tokenize=False, add_generation_prompt=True)
            for s in chunk
        ]
        inputs = processor(
            text=prompts, images=[load_image(s["image"]) for s in chunk], return_tensors="pt", padding=True
        ).to(model.device)
        generated = model.generate(**inputs, max_new_tokens=12, do_sample=False)
        answers += processor.batch_decode(generated[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    return [answer.strip() for answer in answers]


def report_for(samples, answers, model_name, seconds):
    """A report in the shape SatQuery's evaluate_benchmark.py writes."""
    outcomes, mistakes = [], []
    for sample, given in zip(samples, answers):
        correct = answers_match(given, sample["answer"])
        outcomes.append((sample["type"], correct, token_f1(given, sample["answer"])))
        if not correct and len(mistakes) < 25:
            mistakes.append({"id": sample["id"], "type": sample["type"], "question": sample["question"],
                             "expected": sample["answer"], "answered": given})
    return {
        "model": model_name,
        "dataset": "rsvqa",
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(seconds, 1),
        "selection": {
            "questions_in_file": len(load_split("test")),
            "question_types": sorted(TYPES),
            "method": f"random sample of {len(samples)} (seed {SEED})",
            "images": len({s["image"] for s in samples}),
        },
        **summarise(outcomes),
        "failed_calls": 0,
        "failures": [],
        "mistakes": mistakes,
    }


# %% [markdown]
# ## The base model, before fine-tuning

# %%
started = time.perf_counter()
base_report = report_for(eval_set, answer_all(eval_set), f"base:{BASE_MODEL}", time.perf_counter() - started)
print(f"base model: overall {base_report['overall_accuracy']:.1%}, per type",
      {k: f"{v['accuracy']:.1%}" for k, v in base_report["per_type"].items()})

# %% [markdown]
# ## LoRA fine-tuning
#
# Only the language model's attention and MLP projections are adapted; the
# vision encoder is left as it is. Loss is computed on the answer alone.

# %%
from peft import LoraConfig, get_peft_model
from transformers import Trainer, TrainingArguments

model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
model.enable_input_require_grads()
model = get_peft_model(model, LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
))
model.print_trainable_parameters()


def collate(batch):
    processor.tokenizer.padding_side = "right"
    images = [load_image(s["image"]) for s in batch]
    full = [processor.apply_chat_template(conversation(s, True), tokenize=False) for s in batch]
    inputs = processor(text=full, images=images, return_tensors="pt", padding=True)
    labels = inputs["input_ids"].clone()
    labels[inputs["attention_mask"] == 0] = -100
    for row, (sample, image) in enumerate(zip(batch, images)):
        prompt = processor.apply_chat_template(conversation(sample, False), tokenize=False, add_generation_prompt=True)
        prompt_length = processor(text=[prompt], images=[image], return_tensors="pt")["input_ids"].shape[1]
        labels[row, :prompt_length] = -100  # learn the answer, not the question
    inputs["labels"] = labels
    return inputs


trainer = Trainer(
    model=model,
    train_dataset=train_set,
    data_collator=collate,
    args=TrainingArguments(
        output_dir=os.path.join(WORK, "checkpoints"),
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        num_train_epochs=EPOCHS,
        max_steps=MAX_STEPS,
        learning_rate=LEARNING_RATE,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=1 if SMOKE_TEST else 20,
        save_strategy="no",
        fp16=CUDA,
        remove_unused_columns=False,
        # PEFT hides the base model's signature, so the Trainer cannot find
        # the labels argument on its own.
        label_names=["labels"],
        dataloader_num_workers=0 if SMOKE_TEST else 2,
        report_to="none",
        seed=SEED,
    ),
)
trainer.train()

# %% [markdown]
# ## The fine-tuned model, on the same questions

# %%
started = time.perf_counter()
tuned_report = report_for(eval_set, answer_all(eval_set), f"hosted:{SERVED_NAME}", time.perf_counter() - started)
print(f"fine-tuned: overall {tuned_report['overall_accuracy']:.1%} "
      f"(base {base_report['overall_accuracy']:.1%}), per type",
      {k: f"{v['accuracy']:.1%}" for k, v in tuned_report["per_type"].items()})

# %% [markdown]
# ## Package for SatQuery
#
# The zip holds the LoRA adapter, which base model it adapts, and both
# reports. `benchmark_report.json` is recorded under the identity
# `hosted:satquery-qwen2vl-rsvqa`, which is what SatQuery calls the model
# once it is served under that name.

# %%
model.save_pretrained(os.path.join(OUTPUT, "adapter"))
with open(os.path.join(OUTPUT, "served_model.json"), "w", encoding="utf-8") as handle:
    json.dump({"base_model": BASE_MODEL, "served_name": SERVED_NAME, "smoke_test": SMOKE_TEST}, handle, indent=2)
with open(os.path.join(OUTPUT, "benchmark_report.json"), "w", encoding="utf-8") as handle:
    json.dump(tuned_report, handle, indent=2)
with open(os.path.join(OUTPUT, "benchmark_report_base.json"), "w", encoding="utf-8") as handle:
    json.dump(base_report, handle, indent=2)

archive = shutil.make_archive(os.path.join(WORK, SERVED_NAME), "zip", WORK, SERVED_NAME)
shutil.rmtree(os.path.join(WORK, "checkpoints"), ignore_errors=True)
print("download:", archive)
