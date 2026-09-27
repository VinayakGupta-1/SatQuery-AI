"""Measure the vision-language model core on a remote-sensing VQA benchmark.

The datasets are not bundled -- each is several gigabytes and has its own
licence. Download one, point this script at it, and it reports how often the
configured model (SATQUERY_VQA_* settings) answers correctly:

RSVQA (Lobry et al., 2020; https://rsvqa.sylvainlobry.com; the low-resolution
set is https://zenodo.org/records/6344334, about 100 MB)::

    python scripts/evaluate_benchmark.py rsvqa \\
        --questions RSVQA_LR/LR_split_test_questions.json \\
        --answers   RSVQA_LR/LR_split_test_answers.json \\
        --images    RSVQA_LR/Images_LR \\
        --types presence,comp,rural_urban --sample 500 --limit 90 --delay 18

``--sample`` scores a seeded random sample: benchmark files list many
questions per image in a row, so the first 500 can be only five scenes.
``--types`` leaves out RSVQA-LR's ``count`` questions, whose answers are raw
object counts ("403 roads") no model can read from 10 m pixels; VLM
evaluations on RSVQA-LR commonly report the other three types. ``--limit``
scores the first N of the sample. ``--delay`` spaces the calls to the
endpoint's rate limit: on Groq's free tier an image costs about 2,080 input
tokens against 7,000 a minute (hence 18 seconds) and 200,000 a day (hence
about 90 questions per run).

VRSBench VQA, or any benchmark exported as JSON/JSONL records::

    python scripts/evaluate_benchmark.py records --data vrsbench_vqa.json \\
        --image-field image_id --question-field question \\
        --answer-field ground_truth --type-field type --image-root VRSBench/Images

CDVQA (two images per question: give two image fields)::

    python scripts/evaluate_benchmark.py records --data cdvqa_test.jsonl \\
        --image-field image_t1 --image-field image_t2 --image-root CDVQA

The report is written to evaluation_reports/ and copied to
evaluation_reports/latest.json. Answers the same model gives inside SatQuery
then carry this measured accuracy as a confidence factor.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import get_settings  # noqa: E402
from app.evaluation.datasets import DatasetError, load_records, load_rsvqa  # noqa: E402
from app.evaluation.runner import BenchmarkInterrupted, evaluate, model_answerer, select  # noqa: E402
from app.tools.vlm.client import VisionLanguageModel  # noqa: E402
from app.tools.vlm.core import vlm_unavailable_reason  # noqa: E402

REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evaluation_reports")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="format", required=True)

    rsvqa = sub.add_parser("rsvqa", help="the RSVQA questions/answers layout")
    rsvqa.add_argument("--questions", required=True)
    rsvqa.add_argument("--answers", required=True)
    rsvqa.add_argument("--images", required=True)
    rsvqa.add_argument("--image-pattern", default="{img_id}.tif")
    rsvqa.add_argument("--name", default="rsvqa")

    records = sub.add_parser("records", help="flat JSON or JSONL records (VRSBench, CDVQA)")
    records.add_argument("--data", required=True)
    records.add_argument("--image-field", action="append", required=True, dest="image_fields")
    records.add_argument("--question-field", default="question")
    records.add_argument("--answer-field", default="answer")
    records.add_argument("--type-field", default="type")
    records.add_argument("--id-field", default="id")
    records.add_argument("--image-root", default="")
    records.add_argument("--name", default=None)

    for command in (rsvqa, records):
        command.add_argument("--limit", type=int, default=None, help="score only the first N questions")
        command.add_argument("--sample", type=int, default=None, help="score a seeded random sample of N questions")
        command.add_argument("--seed", type=int, default=0, help="seed for --sample (default 0)")
        command.add_argument("--types", default=None, help="comma-separated question types to score, e.g. presence,comp")
        command.add_argument("--delay", type=float, default=0.0, help="minimum seconds between model calls")
        command.add_argument("--out", default=None, help="report path (default: evaluation_reports/)")
        command.add_argument("--no-latest", action="store_true", help="do not update latest.json")

    args = parser.parse_args(argv)

    reason = vlm_unavailable_reason()
    if reason:
        print(f"The vision-language model is not available: {reason}", file=sys.stderr)
        return 2

    try:
        if args.format == "rsvqa":
            samples = load_rsvqa(args.questions, args.answers, args.images, args.image_pattern)
            name = args.name
        else:
            samples = load_records(
                args.data, args.image_fields, args.question_field, args.answer_field,
                args.type_field or None, args.id_field or None, args.image_root,
            )
            name = args.name or os.path.splitext(os.path.basename(args.data))[0]
    except DatasetError as error:
        print(f"Could not load the benchmark: {error}", file=sys.stderr)
        return 2
    types = {kind.strip() for kind in args.types.split(",") if kind.strip()} if args.types else None
    samples, selection = select(samples, args.sample, args.seed, types)
    if not samples:
        print("The benchmark has no usable questions.", file=sys.stderr)
        return 2

    model = VisionLanguageModel(get_settings())
    total = min(len(samples), args.limit or len(samples))
    if total < len(samples):
        # --sample N --limit M scores the first M of that sample: a subset of
        # exactly the questions another run over the full sample measured.
        selection["method"] = f"first {total} of a {selection['method']}"
        selection["images"] = len({image for sample in samples[:total] for image in sample.images})
    print(
        f"Evaluating {model.identity} on {total} {name} question(s) "
        f"({selection['method']}, {selection['images']} image(s))..."
    )

    def progress(done: int, count: int) -> None:
        if done == count or done % 25 == 0:
            print(f"  {done}/{count}", flush=True)

    try:
        report = evaluate(
            samples, model_answerer(model), name, model.identity, args.limit, progress,
            min_interval=args.delay, selection=selection,
        )
    except BenchmarkInterrupted as stopped:
        print(
            f"\n{stopped}\nNo report was written: scoring the unanswered questions as "
            "wrong would measure the quota, not the model. Rerun with a smaller "
            "--limit, or once the quota has reset.",
            file=sys.stderr,
        )
        return 3

    os.makedirs(REPORTS, exist_ok=True)
    out = args.out or os.path.join(REPORTS, f"{name}_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    if not args.no_latest:
        shutil.copyfile(out, os.path.join(REPORTS, "latest.json"))

    print(
        f"\nOverall accuracy {report['overall_accuracy']:.1%}, average per type "
        f"{report['average_accuracy']:.1%}, token F1 {report['mean_token_f1']:.2f} "
        f"over {report['samples']} question(s); {report['failed_calls']} call(s) failed."
    )
    for kind, entry in report["per_type"].items():
        print(f"  {kind:<14} {entry['accuracy']:.1%}  ({entry['samples']})")
    print(f"Report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
