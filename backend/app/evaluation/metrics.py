"""Scoring a model's answers against a benchmark's.

Remote-sensing VQA benchmarks mostly have short answers -- "yes", "no", "12",
"rural" -- and score them by exact match after normalisation. That is what
this module does, with the normalisation made explicit so a reported accuracy
can be reproduced:

* case, surrounding punctuation and a leading article are ignored;
* a yes/no reference is matched on the yes/no the answer leads with;
* a numeric reference is matched on the first number in the answer, with
  number words ("three") read as digits.

Open-ended answers (VRSBench captions and long answers) are also given a
token-overlap F1, the usual lenient companion to exact match; the VRSBench
authors grade those answers with a language model, which is not reproduced
here, so F1 is reported as what it is rather than as their metric.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

NUMBER_WORDS = {
    "zero": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
_ARTICLE = re.compile(r"^(a|an|the)\s+")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def normalise(text: str) -> str:
    """Lower-case, trim punctuation and a leading article."""
    text = str(text).strip().lower()
    text = re.sub(r"^[\W_]+|[\W_]+$", "", text)
    return _ARTICLE.sub("", text).strip()


def _first_number(text: str) -> float | None:
    match = _NUMBER.search(text)
    if match:
        return float(match.group(0))
    for word in re.findall(r"[a-z]+", text):
        if word in NUMBER_WORDS:
            return float(NUMBER_WORDS[word])
    return None


def answers_match(answer: str, reference: str) -> bool:
    """Whether a model's ``answer`` counts as the benchmark's ``reference``."""
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


def token_f1(answer: str, reference: str) -> float:
    """Token-overlap F1 between two answers, after normalisation."""
    got = normalise(answer).split()
    want = normalise(reference).split()
    if not got or not want:
        return float(got == want)
    common = sum((Counter(got) & Counter(want)).values())
    if common == 0:
        return 0.0
    precision, recall = common / len(got), common / len(want)
    return 2 * precision * recall / (precision + recall)


def summarise(outcomes: Iterable[tuple[str, bool, float]]) -> dict[str, object]:
    """Overall, average-per-type and per-type accuracy from ``(type, correct, f1)``.

    Overall accuracy (OA) weights every question equally; average accuracy
    (AA) weights every question *type* equally, which is how RSVQA reports
    results, so a model cannot look good by answering only the common type.
    """
    per_type: dict[str, list[tuple[bool, float]]] = {}
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
            sum(entry["accuracy"] for entry in breakdown.values()) / len(breakdown)
            if breakdown else 0.0
        ),
        "mean_token_f1": (
            sum(f1 for values in per_type.values() for _, f1 in values) / total if total else 0.0
        ),
        "per_type": breakdown,
    }


__all__ = ["answers_match", "normalise", "summarise", "token_f1"]
