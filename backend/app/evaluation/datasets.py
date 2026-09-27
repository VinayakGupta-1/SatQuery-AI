"""Loading benchmark questions into one shape.

Three benchmarks are named in the architecture, and they ship differently:

*RSVQA* (Lobry et al., 2020) -- a questions file and an answers file, each a
JSON object holding a list, joined on answer ids, with images named by id.
:func:`load_rsvqa` reads that layout directly.

*VRSBench* and *CDVQA* -- flat records, one question per record, one image or
(for CDVQA's change questions) two. :func:`load_records` reads JSON or JSONL
with the field names given as arguments, so the same loader serves both and
any export of them; CDVQA's pair is two image fields.

Every loader fails loudly on a record it cannot read, naming the field it
expected, rather than silently scoring a benchmark on half its questions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


class DatasetError(Exception):
    """A benchmark file is not in the layout it was declared to be in."""


@dataclass
class Sample:
    """One benchmark question with its image(s) and reference answer."""

    id: str
    images: list[str]
    question: str
    answer: str
    type: str = "all"
    extra: dict = field(default_factory=dict)


def _load_json(path: str) -> object:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        raise DatasetError(f"Could not read {path}: {error}") from error


def load_rsvqa(
    questions_path: str,
    answers_path: str,
    images_dir: str,
    image_pattern: str = "{img_id}.tif",
) -> list[Sample]:
    """Read an RSVQA split: questions and answers files plus the image folder."""
    questions = _load_json(questions_path)
    answers = _load_json(answers_path)
    if not isinstance(questions, dict) or not isinstance(questions.get("questions"), list):
        raise DatasetError(f"{questions_path} should hold {{'questions': [...]}}.")
    if not isinstance(answers, dict) or not isinstance(answers.get("answers"), list):
        raise DatasetError(f"{answers_path} should hold {{'answers': [...]}}.")

    answer_by_id = {
        entry.get("id"): entry.get("answer")
        for entry in answers["answers"]
        if isinstance(entry, dict) and entry.get("active", True)
    }
    samples: list[Sample] = []
    for entry in questions["questions"]:
        if not isinstance(entry, dict) or not entry.get("active", True):
            continue
        for key in ("id", "img_id", "question", "answers_ids"):
            if key not in entry:
                raise DatasetError(f"An RSVQA question has no '{key}' field: {entry}")
        ids = entry["answers_ids"] if isinstance(entry["answers_ids"], list) else [entry["answers_ids"]]
        answer = next((answer_by_id[i] for i in ids if answer_by_id.get(i) is not None), None)
        if answer is None:
            continue
        samples.append(
            Sample(
                id=str(entry["id"]),
                images=[os.path.join(images_dir, image_pattern.format(img_id=entry["img_id"]))],
                question=str(entry["question"]),
                answer=str(answer),
                type=str(entry.get("type", "all")),
            )
        )
    return samples


def load_records(
    path: str,
    image_fields: list[str],
    question_field: str = "question",
    answer_field: str = "answer",
    type_field: str | None = "type",
    id_field: str | None = "id",
    image_root: str = "",
) -> list[Sample]:
    """Read flat JSON (a list) or JSONL records into samples."""
    if path.lower().endswith(".jsonl"):
        records = []
        try:
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    if line.strip():
                        try:
                            records.append(json.loads(line))
                        except ValueError as error:
                            raise DatasetError(f"{path} line {number}: {error}") from error
        except OSError as error:
            raise DatasetError(f"Could not read {path}: {error}") from error
    else:
        loaded = _load_json(path)
        if isinstance(loaded, dict):
            loaded = loaded.get("data")
        if not isinstance(loaded, list):
            raise DatasetError(f"{path} should hold a list of records (or {{'data': [...]}}).")
        records = loaded

    samples: list[Sample] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise DatasetError(f"Record {index} in {path} is not an object.")
        for key in [*image_fields, question_field, answer_field]:
            if key not in record:
                raise DatasetError(f"Record {index} in {path} has no '{key}' field.")
        samples.append(
            Sample(
                id=str(record.get(id_field, index)) if id_field else str(index),
                images=[os.path.join(image_root, str(record[key])) for key in image_fields],
                question=str(record[question_field]),
                answer=str(record[answer_field]),
                type=str(record.get(type_field, "all")) if type_field else "all",
            )
        )
    return samples


__all__ = ["DatasetError", "Sample", "load_records", "load_rsvqa"]
