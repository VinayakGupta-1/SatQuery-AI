"""Running a benchmark through the vision-language model core.

Each sample's image(s) are shown to the configured model exactly as SatQuery
shows them in production -- a GeoTIFF is rendered by the same code, an
ordinary PNG or JPEG benchmark tile is sent as it is -- with the question and
an instruction to answer in a word or a number, which is the form these
benchmarks' reference answers take. Answers are scored by
:mod:`app.evaluation.metrics`.

The report records which model was measured, on what, and how it did, and is
what confidence scoring reads: once a model has a measured accuracy, answers
it writes carry that accuracy as a confidence factor instead of going
unrated.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Callable

from app.evaluation.datasets import Sample
from app.evaluation.metrics import answers_match, summarise, token_f1
from app.tools.base import ToolExecutionError
from app.tools.raster.io import open_raster
from app.tools.raster.model import RasterError
from app.tools.raster.render import render_preview
from app.tools.vlm.client import RateLimited, VisionLanguageModel

ENCODED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

SHORT_ANSWER_PROMPT = (
    "You are answering a question about {what}. Reply with a single word or "
    "number and nothing else -- for example: yes, no, 3, urban.\n\nQuestion: {question}"
)

AnswerFunction = Callable[[Sample], str]


def picture(path: str) -> bytes:
    """The bytes a model is shown for one benchmark image."""
    if os.path.splitext(path)[1].lower() in ENCODED_IMAGE_EXTENSIONS:
        with open(path, "rb") as handle:
            return handle.read()
    try:
        return render_preview(open_raster(path)).png
    except RasterError as error:
        raise ToolExecutionError(f"Could not read benchmark image {path}: {error}") from error


def model_answerer(model: VisionLanguageModel | None = None) -> AnswerFunction:
    """An answer function backed by the configured vision-language model."""
    model = model or VisionLanguageModel()

    def answer(sample: Sample) -> str:
        what = (
            "a satellite image"
            if len(sample.images) == 1
            else "two satellite images of the same place, the earlier first"
        )
        return model.complete(
            SHORT_ANSWER_PROMPT.format(what=what, question=sample.question),
            [picture(path) for path in sample.images],
            max_tokens=12,
        )

    return answer


class BenchmarkInterrupted(Exception):
    """The endpoint stopped answering for longer than a run can wait."""

    def __init__(self, answered: int, total: int, reason: str) -> None:
        self.answered, self.total, self.reason = answered, total, reason
        super().__init__(f"Stopped after {answered} of {total} questions: {reason}")


def select(
    samples: list[Sample],
    sample_size: int | None = None,
    seed: int = 0,
    types: set[str] | None = None,
) -> tuple[list[Sample], dict[str, object]]:
    """Choose which questions to score, reproducibly, and say how.

    Benchmark files list many questions per image in a row, so "the first
    500" can be five scenes. A seeded random sample spreads the questions over
    the benchmark and gives the same questions on every run.
    """
    pool = [sample for sample in samples if not types or sample.type in types]
    if sample_size and sample_size < len(pool):
        chosen = random.Random(seed).sample(pool, sample_size)
        how = f"random sample of {sample_size} (seed {seed})"
    else:
        chosen = pool
        how = "every question"
    return chosen, {
        "questions_in_file": len(samples),
        "question_types": sorted(types) if types else "all",
        "method": how,
        "images": len({image for sample in chosen for image in sample.images}),
    }


def load_checkpoint(path: str | None, model: str) -> dict[str, str]:
    """Answers ``model`` already gave, by question id, from a checkpoint file.

    Lines written for another model are ignored, so one file can never mix
    two models' answers into one score.
    """
    if not path or not os.path.exists(path):
        return {}
    answers: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # a line cut off when the process was killed
            if isinstance(entry, dict) and entry.get("model") == model and "id" in entry:
                answers[str(entry["id"])] = str(entry.get("answered", ""))
    return answers


def evaluate(
    samples: list[Sample],
    answer: AnswerFunction,
    dataset: str,
    model: str,
    limit: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    min_interval: float = 0.0,
    selection: dict[str, object] | None = None,
    checkpoint: str | None = None,
) -> dict[str, object]:
    """Answer every sample and score the answers into a report.

    ``min_interval`` spaces the calls at least that many seconds apart, to
    stay inside a hosted endpoint's requests-per-minute limit.

    ``checkpoint`` names a file every answer is appended to as it arrives.
    A free-tier quota can run out mid-run; with a checkpoint, running the same
    command again reuses the saved answers and asks only the remaining
    questions, instead of spending the quota on the same questions again.
    Failed calls are not saved, so they are retried.
    """
    chosen = samples[:limit] if limit else samples
    saved = load_checkpoint(checkpoint, model)
    outcomes: list[tuple[str, bool, float]] = []
    mistakes: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    reused = 0
    started = time.perf_counter()
    last_call = float("-inf")

    for index, sample in enumerate(chosen, start=1):
        if sample.id in saved:
            given = saved[sample.id]
            reused += 1
        else:
            wait = last_call + min_interval - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            last_call = time.perf_counter()
            try:
                given = answer(sample)
            except RateLimited as error:
                # A quota that outlasts the run is not the model being wrong:
                # scoring every remaining question as a failure would report
                # an accuracy that measures the quota. Stop instead.
                raise BenchmarkInterrupted(index - 1, len(chosen), str(error)) from None
            except ToolExecutionError as error:
                # A failed call is scored wrong, not skipped: skipping would let
                # an unreliable endpoint inflate its own accuracy.
                given = ""
                failures.append({"id": sample.id, "error": str(error)})
            else:
                if checkpoint:
                    _append(checkpoint, {"model": model, "id": sample.id, "answered": given})
        correct = answers_match(given, sample.answer)
        outcomes.append((sample.type, correct, token_f1(given, sample.answer)))
        if not correct and len(mistakes) < 25:
            mistakes.append(
                {"id": sample.id, "type": sample.type, "question": sample.question,
                 "expected": sample.answer, "answered": given}
            )
        if progress:
            progress(index, len(chosen))

    report: dict[str, object] = {
        "model": model,
        "dataset": dataset,
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.perf_counter() - started, 1),
        "selection": selection or {"method": f"first {len(chosen)}" if limit else "every question"},
        **summarise(outcomes),
        "failed_calls": len(failures),
        "answers_reused_from_checkpoint": reused,
        "failures": failures[:25],
        "mistakes": mistakes,
    }
    return report


def _append(path: str, entry: dict[str, str]) -> None:
    """Add one answer to the checkpoint and make sure it reached the disk."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "BenchmarkInterrupted",
    "evaluate",
    "load_checkpoint",
    "model_answerer",
    "picture",
    "select",
]
