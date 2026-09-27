"""Confidence scoring: how far an answer can be trusted, built from measurements.

A confidence number is only useful if a reader can ask "why?" and get a
concrete answer. So the score here is assembled from factors that are each a
measured quantity:

``interpretation``
    How clearly the question mapped onto the capability that answered it.
``coverage``
    The share of the analysed area that could actually be observed -- cloud,
    nodata and undefined pixels lower it.
``agreement``
    For optical + SAR fusion: how well the two sensors agree beyond chance
    (Cohen's kappa over pixels both observed).
``model_accuracy``
    For an answer written by the vision-language model: that model's measured
    accuracy on a benchmark, read from the report
    ``scripts/evaluate_benchmark.py`` writes.

The score is the weakest factor -- a chain is as strong as its weakest link,
and "confidence is 41% because 59% of the scene was cloud" is an explanation a
user can act on. It is a reliability indicator, not a calibrated probability.

A model-generated answer from a model nobody has benchmarked gets *no* score:
its level is ``unrated``. Inventing a number for it would be exactly the kind
of fabrication this system exists to avoid.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from app.config.settings import get_settings
from app.schemas.results import ConfidenceFactor, ConfidenceReport

HIGH = 0.8
MEDIUM = 0.5

#: Where the benchmark script writes its latest report by default.
DEFAULT_REPORT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "evaluation_reports",
    "latest.json",
)


@lru_cache(maxsize=8)
def _read_report(path: str, modified: float) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def benchmark_for(model_identity: str | None) -> dict[str, Any] | None:
    """The latest benchmark report for ``model_identity``, if there is one."""
    if not model_identity:
        return None
    path = get_settings().vqa_benchmark_report or DEFAULT_REPORT
    try:
        modified = os.path.getmtime(path)
    except OSError:
        return None
    report = _read_report(path, modified)
    if not report or report.get("model") != model_identity:
        return None
    if not isinstance(report.get("overall_accuracy"), (int, float)):
        return None
    return report


def _level(score: float) -> str:
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"


def assess(
    interpretation: float | None,
    statistics: dict[str, Any] | None,
    engine: str,
    model_identity: str | None = None,
) -> ConfidenceReport:
    """Build the confidence report for one completed answer."""
    statistics = statistics or {}
    factors: list[ConfidenceFactor] = []

    if interpretation is not None:
        factors.append(
            ConfidenceFactor(
                name="interpretation",
                score=max(0.0, min(1.0, interpretation)),
                detail="How clearly the question mapped onto the capability that answered it.",
            )
        )
    coverage = statistics.get("valid_fraction")
    if isinstance(coverage, (int, float)):
        factors.append(
            ConfidenceFactor(
                name="coverage",
                score=max(0.0, min(1.0, float(coverage))),
                detail=(
                    f"{coverage:.0%} of the analysed area could be observed; the rest was "
                    "cloud, nodata or undefined."
                ),
            )
        )
    kappa = statistics.get("kappa")
    if isinstance(kappa, (int, float)):
        factors.append(
            ConfidenceFactor(
                name="agreement",
                score=max(0.0, min(1.0, float(kappa))),
                detail=(
                    f"Optical and radar agree beyond chance with Cohen's kappa {kappa:.2f}, "
                    "over the pixels both could observe."
                ),
            )
        )

    model_generated = engine in {"vlm", "hybrid"}
    if model_generated:
        report = benchmark_for(model_identity)
        if report is None:
            return ConfidenceReport(
                score=None,
                level="unrated",
                basis=(
                    "The answer was written by a vision-language model whose accuracy has "
                    "not been measured here, so it is not given a score."
                    + (" The change figures it was given are measured." if engine == "hybrid" else "")
                    + " Run scripts/evaluate_benchmark.py to rate it."
                ),
                factors=factors,
            )
        accuracy = float(report["overall_accuracy"])
        factors.append(
            ConfidenceFactor(
                name="model_accuracy",
                score=max(0.0, min(1.0, accuracy)),
                detail=(
                    f"{model_identity} answered {accuracy:.0%} of {report.get('samples', '?')} "
                    f"{report.get('dataset', 'benchmark')} questions correctly."
                ),
            )
        )

    if not factors:
        return ConfidenceReport(score=None, level="unrated", basis="Nothing measurable to score.")

    weakest = min(factors, key=lambda factor: factor.score)
    return ConfidenceReport(
        score=weakest.score,
        level=_level(weakest.score),
        basis=f"Limited by {weakest.name}: {weakest.detail}",
        factors=factors,
    )


__all__ = ["assess", "benchmark_for"]
