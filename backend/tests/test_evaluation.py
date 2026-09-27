"""Tests for benchmark evaluation: loading, scoring, running, reporting.

No benchmark is downloaded and no model is called. The loaders are given
small files in each benchmark's real layout, the scorer is checked against
answers worked out by hand, and the runner is driven by a stand-in answer
function -- so what is under test is that a reported accuracy means what it
says.
"""

from __future__ import annotations

import importlib.util
import json
import os

import pytest

from app.config.settings import reset_settings
from app.evaluation.datasets import DatasetError, Sample, load_records, load_rsvqa
from app.evaluation.metrics import answers_match, normalise, summarise, token_f1
from app.evaluation.runner import evaluate, model_answerer, picture
from app.tools.base import ToolExecutionError
from app.tools.vlm import client
from app.tools.vlm.client import VisionLanguageModel
from tests.conftest import make_band

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# SCORING
# ============================================================
def test_normalisation_ignores_case_punctuation_and_articles():
    assert normalise("  The Urban. ") == "urban"
    assert normalise("A river!") == "river"


@pytest.mark.parametrize(
    "answer, reference, expected",
    [
        ("Yes, there is a river.", "yes", True),
        ("No.", "yes", False),
        ("yesterday", "yes", False),
        ("3 buildings", "3", True),
        ("There are three.", "3", True),
        ("4", "3", False),
        ("Rural", "rural", True),
        ("urban", "rural", False),
        ("", "yes", False),
    ],
)
def test_answers_are_matched_the_way_the_benchmarks_score_them(answer, reference, expected):
    assert answers_match(answer, reference) is expected


def test_token_f1_is_lenient_about_extra_words():
    assert token_f1("a large river", "river") == pytest.approx(2 / 3)
    assert token_f1("forest", "river") == 0.0
    assert token_f1("", "") == 1.0


def test_average_accuracy_weights_every_question_type_equally():
    outcomes = [("presence", True, 1.0)] * 3 + [("presence", False, 0.0), ("count", False, 0.0)]
    report = summarise(outcomes)
    assert report["samples"] == 5
    assert report["overall_accuracy"] == pytest.approx(3 / 5)
    assert report["average_accuracy"] == pytest.approx((3 / 4 + 0) / 2)
    assert report["per_type"]["presence"] == {"samples": 4, "accuracy": 0.75, "token_f1": 0.75}


# ============================================================
# LOADING
# ============================================================
def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def test_rsvqa_questions_and_answers_are_joined(tmp_path):
    questions = write_json(tmp_path / "q.json", {"questions": [
        {"id": 1, "img_id": 7, "question": "Is there a road?", "answers_ids": [10], "type": "presence"},
        {"id": 2, "img_id": 7, "question": "Inactive?", "answers_ids": [11], "active": False},
        {"id": 3, "img_id": 8, "question": "How many buildings?", "answers_ids": 12, "type": "count"},
    ]})
    answers = write_json(tmp_path / "a.json", {"answers": [
        {"id": 10, "answer": "yes"}, {"id": 11, "answer": "no"}, {"id": 12, "answer": "4"},
    ]})

    samples = load_rsvqa(questions, answers, "imgs")

    assert [(s.id, s.answer, s.type) for s in samples] == [("1", "yes", "presence"), ("3", "4", "count")]
    assert samples[0].images == [os.path.join("imgs", "7.tif")]


def test_an_rsvqa_file_in_the_wrong_layout_is_refused(tmp_path):
    bad = write_json(tmp_path / "q.json", [{"question": "?"}])
    answers = write_json(tmp_path / "a.json", {"answers": []})
    with pytest.raises(DatasetError, match="should hold"):
        load_rsvqa(bad, answers, "imgs")

    missing = write_json(tmp_path / "q2.json", {"questions": [{"id": 1, "question": "?", "answers_ids": [1]}]})
    with pytest.raises(DatasetError, match="no 'img_id' field"):
        load_rsvqa(missing, answers, "imgs")


def test_cdvqa_records_carry_both_dates(tmp_path):
    path = tmp_path / "cdvqa.jsonl"
    path.write_text(
        '{"id": "a", "image_t1": "t1/1.png", "image_t2": "t2/1.png", "question": "Did it change?", "answer": "yes", "type": "change"}\n\n',
        encoding="utf-8",
    )
    (sample,) = load_records(str(path), ["image_t1", "image_t2"], image_root="root")
    assert sample.images == [os.path.join("root", "t1/1.png"), os.path.join("root", "t2/1.png")]
    assert sample.type == "change"


def test_records_wrapped_in_data_are_read(tmp_path):
    path = write_json(tmp_path / "vrs.json", {"data": [{"image_id": "x.png", "question": "q", "ground_truth": "a"}]})
    (sample,) = load_records(path, ["image_id"], answer_field="ground_truth", id_field=None)
    assert (sample.id, sample.answer, sample.type) == ("0", "a", "all")


def test_a_broken_record_is_named_not_skipped(tmp_path):
    path = write_json(tmp_path / "vrs.json", [{"image": "x.png", "question": "q"}])
    with pytest.raises(DatasetError, match="Record 0 .* no 'answer' field"):
        load_records(path, ["image"])

    jsonl = tmp_path / "bad.jsonl"
    jsonl.write_text('{"image": "x", "question": "q", "answer": "a"}\n{not json\n', encoding="utf-8")
    with pytest.raises(DatasetError, match="line 2"):
        load_records(str(jsonl), ["image"])


# ============================================================
# RUNNING
# ============================================================
def samples():
    return [
        Sample(id="1", images=["a.png"], question="Is there water?", answer="yes", type="presence"),
        Sample(id="2", images=["b.png"], question="How many ponds?", answer="2", type="count"),
        Sample(id="3", images=["c.png"], question="Is it urban?", answer="no", type="presence"),
    ]


def test_a_failed_call_is_scored_wrong_not_skipped():
    replies = {"1": "Yes.", "2": "two"}

    def answer(sample):
        if sample.id not in replies:
            raise ToolExecutionError("The vision model could not be reached.")
        return replies[sample.id]

    progress = []
    report = evaluate(samples(), answer, "tiny", "fake:model", progress=lambda i, n: progress.append((i, n)))

    assert report["samples"] == 3
    assert report["overall_accuracy"] == pytest.approx(2 / 3)
    assert report["failed_calls"] == 1
    assert report["failures"][0]["id"] == "3"
    assert report["mistakes"] == [{
        "id": "3", "type": "presence", "question": "Is it urban?", "expected": "no", "answered": "",
    }]
    assert progress[-1] == (3, 3)
    assert report["model"] == "fake:model" and report["dataset"] == "tiny"


def test_a_limit_scores_only_the_first_questions():
    report = evaluate(samples(), lambda sample: "yes", "tiny", "fake:model", limit=1)
    assert report["samples"] == 1 and report["overall_accuracy"] == 1.0


def test_encoded_tiles_are_sent_as_they_are_and_geotiffs_are_rendered(tmp_path, raster_factory):
    png = tmp_path / "tile.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nrest")
    assert picture(str(png)) == b"\x89PNG\r\n\x1a\nrest"

    tif = raster_factory("tile.tif", [make_band(n, [1, 2, 3, 4], 2, 2) for n in ("B2", "B3", "B4")])
    assert picture(tif)[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_model_is_asked_for_a_one_word_answer(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(
        client, "post_json",
        lambda url, payload, key, timeout: sent.append(payload) or {"choices": [{"message": {"content": "yes"}}]},
    )
    first, second = tmp_path / "1.png", tmp_path / "2.png"
    for path in (first, second):
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
    pair = Sample(id="p", images=[str(first), str(second)], question="Did it change?", answer="yes")

    assert model_answerer(VisionLanguageModel())(pair) == "yes"
    (payload,) = sent
    assert payload["max_tokens"] == 12
    prompt = payload["messages"][0]["content"][0]["text"]
    assert "single word or number" in prompt and "the earlier first" in prompt
    assert len(payload["messages"][0]["content"]) == 3


# ============================================================
# THE SCRIPT
# ============================================================
def load_script():
    spec = importlib.util.spec_from_file_location(
        "evaluate_benchmark", os.path.join(BACKEND, "scripts", "evaluate_benchmark.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_refuses_to_run_while_the_model_is_off(tmp_path, capsys):
    script = load_script()
    data = write_json(tmp_path / "d.json", [])
    assert script.main(["records", "--data", data, "--image-field", "image"]) == 2
    assert "not available" in capsys.readouterr().err


def test_the_script_writes_a_report_confidence_scoring_can_read(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SATQUERY_VQA_ENABLED", "true")
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "rules")
    reset_settings()
    try:
        monkeypatch.setattr(
            client, "post_json",
            lambda url, payload, key, timeout: {"choices": [{"message": {"content": "yes"}}]},
        )
        tile = tmp_path / "t.png"
        tile.write_bytes(b"\x89PNG\r\n\x1a\n")
        data = write_json(tmp_path / "bench.json", [
            {"id": 1, "image": "t.png", "question": "Water?", "answer": "yes", "type": "presence"},
            {"id": 2, "image": "t.png", "question": "Urban?", "answer": "no", "type": "presence"},
        ])
        script = load_script()
        monkeypatch.setattr(script, "REPORTS", str(tmp_path / "reports"))

        assert script.main(["records", "--data", data, "--image-field", "image", "--image-root", str(tmp_path)]) == 0
        latest = tmp_path / "reports" / "latest.json"
        report = json.loads(latest.read_text(encoding="utf-8"))
        assert report["overall_accuracy"] == 0.5
        assert report["dataset"] == "bench"
        assert "Overall accuracy 50.0%" in capsys.readouterr().out

        from app.controller.result_integration.confidence import benchmark_for

        monkeypatch.setenv("SATQUERY_VQA_BENCHMARK_REPORT", str(latest))
        reset_settings()
        assert benchmark_for(report["model"])["overall_accuracy"] == 0.5
        assert benchmark_for("hosted:some-other-model") is None
    finally:
        reset_settings()


# ============================================================
# CHOOSING WHICH QUESTIONS TO SCORE
# ============================================================
def many_samples():
    # Ten images, four questions each, listed image by image as benchmarks do.
    return [
        Sample(id=f"{image}-{q}", images=[f"{image}.tif"], question="?", answer="yes",
               type=("count" if q == 3 else "presence"))
        for image in range(10) for q in range(4)
    ]


def test_a_seeded_sample_is_spread_out_and_reproducible():
    from app.evaluation.runner import select

    first, selection = select(many_samples(), sample_size=8, seed=3)
    again, _ = select(many_samples(), sample_size=8, seed=3)
    other, _ = select(many_samples(), sample_size=8, seed=4)

    assert [s.id for s in first] == [s.id for s in again]
    assert [s.id for s in first] != [s.id for s in other]
    assert selection["images"] > 2  # "the first 8" would be exactly 2 images
    assert selection["method"] == "random sample of 8 (seed 3)"


def test_question_types_can_be_left_out():
    from app.evaluation.runner import select

    chosen, selection = select(many_samples(), types={"presence"})
    assert len(chosen) == 30 and {s.type for s in chosen} == {"presence"}
    assert selection["question_types"] == ["presence"]
    assert selection["method"] == "every question"


def test_calls_are_spaced_to_respect_a_rate_limit(monkeypatch):
    from app.evaluation import runner

    clock = [0.0]
    waits = []
    monkeypatch.setattr(runner.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(runner.time, "sleep", lambda s: (waits.append(round(s, 3)), clock.__setitem__(0, clock[0] + s)))

    def answer(sample):
        clock[0] += 0.5  # each call takes half a second
        return "yes"

    report = evaluate(samples(), answer, "tiny", "fake:model", min_interval=2.0, selection={"method": "x"})
    assert waits == [1.5, 1.5]  # the first call goes at once
    assert report["selection"] == {"method": "x"}


def test_a_limited_run_says_it_scored_part_of_the_sample(monkeypatch, tmp_path):
    monkeypatch.setenv("SATQUERY_VQA_ENABLED", "true")
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "rules")
    reset_settings()
    try:
        monkeypatch.setattr(
            client, "post_json",
            lambda url, payload, key, timeout: {"choices": [{"message": {"content": "yes"}}]},
        )
        (tmp_path / "t.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        data = write_json(tmp_path / "bench.json", [
            {"id": i, "image": "t.png", "question": "?", "answer": "yes", "type": "presence"} for i in range(6)
        ])
        script = load_script()
        monkeypatch.setattr(script, "REPORTS", str(tmp_path / "reports"))
        out = tmp_path / "report.json"
        assert script.main([
            "records", "--data", data, "--image-field", "image", "--image-root", str(tmp_path),
            "--sample", "4", "--limit", "2", "--out", str(out), "--no-latest",
        ]) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["samples"] == 2
        assert report["selection"]["method"] == "first 2 of a random sample of 4 (seed 0)"
    finally:
        reset_settings()


def test_an_exhausted_quota_stops_the_run_instead_of_scoring_it():
    from app.evaluation.runner import BenchmarkInterrupted
    from app.tools.vlm.client import RateLimited

    def answer(sample):
        if sample.id == "2":
            raise RateLimited(400.0)
        return "yes"

    with pytest.raises(BenchmarkInterrupted) as stopped:
        evaluate(samples(), answer, "tiny", "fake:model")
    assert (stopped.value.answered, stopped.value.total) == (1, 3)
    assert "quota" in str(stopped.value)


def test_the_script_writes_no_report_when_the_quota_runs_out(monkeypatch, tmp_path, capsys):
    from app.tools.vlm.client import RateLimited

    monkeypatch.setenv("SATQUERY_VQA_ENABLED", "true")
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "rules")
    reset_settings()
    try:
        def post(url, payload, key, timeout):
            raise RateLimited(400.0)

        monkeypatch.setattr(client, "post_json", post)
        (tmp_path / "t.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        data = write_json(tmp_path / "bench.json", [
            {"id": i, "image": "t.png", "question": "?", "answer": "yes", "type": "presence"} for i in range(3)
        ])
        script = load_script()
        monkeypatch.setattr(script, "REPORTS", str(tmp_path / "reports"))
        assert script.main(["records", "--data", data, "--image-field", "image", "--image-root", str(tmp_path)]) == 3
        assert not (tmp_path / "reports").exists()
        err = capsys.readouterr().err
        assert "Stopped after 0 of 3 questions" in err and "No report was written" in err
    finally:
        reset_settings()
