"""Tests for confidence scoring.

The score is the weakest measured factor, so every test checks both the
number and the sentence explaining it: a confidence a reader cannot trace to
a measurement is not worth reporting.
"""

from __future__ import annotations

import json
import os

import pytest

from app.config.settings import reset_settings
from app.controller.result_integration.confidence import assess, benchmark_for


@pytest.fixture
def benchmark(monkeypatch, tmp_path):
    """Point confidence scoring at a benchmark report written for the test."""

    def write(report):
        path = tmp_path / "latest.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        monkeypatch.setenv("SATQUERY_VQA_BENCHMARK_REPORT", str(path))
        reset_settings()
        return path

    yield write
    reset_settings()


def test_the_score_is_the_weakest_factor_and_says_which():
    report = assess(0.9, {"valid_fraction": 0.41}, "deterministic")
    assert report.score == pytest.approx(0.41)
    assert report.level == "low"
    assert report.basis.startswith("Limited by coverage: 41% of the analysed area")
    assert [factor.name for factor in report.factors] == ["interpretation", "coverage"]


@pytest.mark.parametrize("coverage, level", [(1.0, "high"), (0.8, "high"), (0.79, "medium"), (0.5, "medium"), (0.49, "low")])
def test_levels_follow_the_score(coverage, level):
    assert assess(None, {"valid_fraction": coverage}, "deterministic").level == level


def test_sensor_disagreement_lowers_confidence_and_negative_kappa_is_clamped():
    report = assess(0.9, {"valid_fraction": 0.95, "kappa": -0.2}, "deterministic")
    assert report.score == 0.0
    assert "Cohen's kappa -0.20" in report.basis


def test_nothing_measurable_is_unrated_not_scored():
    report = assess(None, {}, "deterministic")
    assert report.score is None and report.level == "unrated"


def test_an_unbenchmarked_model_answer_is_unrated(monkeypatch, tmp_path):
    monkeypatch.setenv("SATQUERY_VQA_BENCHMARK_REPORT", str(tmp_path / "missing.json"))
    reset_settings()
    try:
        report = assess(0.9, {"valid_fraction": 1.0}, "vlm", "hosted:model")
    finally:
        reset_settings()
    assert report.score is None
    assert report.level == "unrated"
    assert "not been measured" in report.basis
    # The measured factors are still shown; only the score is withheld.
    assert {factor.name for factor in report.factors} == {"interpretation", "coverage"}


def test_a_benchmarked_model_is_scored_by_its_measured_accuracy(benchmark):
    benchmark({"model": "hosted:model", "dataset": "rsvqa", "samples": 200, "overall_accuracy": 0.64})
    report = assess(0.9, {}, "vlm", "hosted:model")
    assert report.score == pytest.approx(0.64)
    assert report.level == "medium"
    assert "answered 64% of 200 rsvqa questions" in report.basis


def test_a_report_for_another_model_does_not_count(benchmark):
    benchmark({"model": "hosted:other", "overall_accuracy": 0.99})
    assert benchmark_for("hosted:model") is None
    assert assess(0.9, {}, "hybrid", "hosted:model").level == "unrated"


def test_a_report_without_an_accuracy_is_ignored(benchmark):
    benchmark({"model": "hosted:model"})
    assert benchmark_for("hosted:model") is None


def test_a_rewritten_report_is_read_again(benchmark):
    path = benchmark({"model": "hosted:model", "overall_accuracy": 0.5})
    assert benchmark_for("hosted:model")["overall_accuracy"] == 0.5
    path.write_text(json.dumps({"model": "hosted:model", "overall_accuracy": 0.75, "padding": "x" * 10}))
    stat = os.stat(path)
    os.utime(path, (stat.st_atime, stat.st_mtime + 5))
    assert benchmark_for("hosted:model")["overall_accuracy"] == 0.75
