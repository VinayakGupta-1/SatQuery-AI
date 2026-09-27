"""Satellite visual question answering, on one scene or an optical + SAR pair.

A free-form question ("is there a river?", "what kind of settlement is
this?") has no formula, so it is answered by the vision-language model
looking at a rendered picture -- and labelled as a model's reading, never
presented as a measurement, with no invented confidence.

Given one optical and one SAR image of the same area, the model is shown both,
each described for what it is: cloud hides the ground from the optical image
but not from radar, and radar is not a photograph. That is cross-modal
question answering; the measured counterpart is ``optical_sar_fusion``.
"""

from __future__ import annotations

from app.tools.base import Artifact, StepLog, ToolExecutionError, ToolOutput, ToolRequest
from app.tools.raster.aoi import open_for_analysis
from app.tools.raster.io import backend_report
from app.tools.raster.render import render_preview, write_preview
from app.tools.sar.backscatter import is_sar
from app.tools.vlm.client import VisionLanguageModel
from app.tools.vlm.core import NOTICE, VisionTool, describe_scene, question_from

MAX_ANSWER_TOKENS = 400

PROMPT = """You are a remote-sensing analyst answering a question about a satellite image.

About the image:
{scene}

Answer using only what is visible. If the question cannot be answered from the image, say so plainly instead of guessing. Do not invent place names, dates, counts or measurements. Answer in at most 120 words.

Question: {question}"""

CROSS_MODAL_PROMPT = """You are a remote-sensing analyst answering a question about one place seen by two sensors.

The first picture is optical:
{optical}

The second picture is radar (SAR) of the same area:
{sar}

Use both: cloud can hide the ground from the optical picture but not from radar, and calm water is dark in radar. Answer using only what is visible. If the question cannot be answered, say so plainly instead of guessing. Do not invent place names, dates, counts or measurements. Answer in at most 120 words.

Question: {question}"""


class SatelliteVQATool(VisionTool):
    """Answers a free-form question with the vision-language model."""

    tool_id = "satellite_vqa"
    result_type = "vqa_answer"

    def preflight(self, request: ToolRequest) -> None:
        question_from(request.parameters)

    def execute(self, request: ToolRequest) -> ToolOutput:
        self.require_available()
        question = question_from(request.parameters)
        references = request.input_references
        if not 1 <= len(references) <= 2:
            raise ToolExecutionError("Visual question answering takes one image, or an optical and a SAR image.")

        log = StepLog()
        model = VisionLanguageModel()
        with log.step("open", "read and clip the imagery"):
            opened = [open_for_analysis(path, request.parameters) for path in references]
        datasets = [dataset for dataset, _ in opened]

        if len(datasets) == 2:
            optical = [d for d in datasets if not is_sar(d)]
            radar = [d for d in datasets if is_sar(d)]
            if len(optical) != 1 or len(radar) != 1:
                raise ToolExecutionError(
                    "Two images are read together only as one optical and one SAR "
                    "image of the same area. For two dates, ask what changed."
                )
            with log.step("render", "true colour and radar pictures"):
                pictures = [render_preview(optical[0]), render_preview(radar[0])]
            prompt = CROSS_MODAL_PROMPT.format(
                optical=describe_scene(optical[0], pictures[0], "The optical picture"),
                sar=describe_scene(radar[0], pictures[1], "The radar picture"),
                question=question,
            )
            ordered = [optical[0], radar[0]]
            ids = ["vqa_preview_optical", "vqa_preview_sar"]
        else:
            with log.step("render", "picture for the model"):
                pictures = [render_preview(datasets[0])]
            prompt = PROMPT.format(scene=describe_scene(datasets[0], pictures[0]), question=question)
            ordered = datasets
            ids = ["vqa_preview"]

        with log.step("ask_model", model.identity):
            answer = model.complete(prompt, [picture.png for picture in pictures], max_tokens=MAX_ANSWER_TOKENS)

        artifacts: list[Artifact] = []
        if request.parameters.get("write_raster", True):
            artifacts = [
                write_preview(request, dataset, dataset.path or "scene", artifact_id, preview=picture)
                for dataset, picture, artifact_id in zip(ordered, pictures, ids)
            ]

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "question": question,
                "answer": answer,
                "model": model.model,
                "provider": model.provider,
                "cross_modal": len(datasets) == 2,
                "rendering": pictures[0].kind,
                "rendering_description": "; ".join(p.description for p in pictures),
                "preview_size": [pictures[0].width, pictures[0].height],
                "notice": NOTICE,
            },
            artifacts=artifacts,
            metadata={
                "source": ordered[0].describe(),
                "sensor": ordered[0].metadata.get("sensor"),
                "aoi": opened[0][1],
                "vlm": model.identity,
                "steps": log.steps,
                **backend_report(),
            },
        )


__all__ = ["SatelliteVQATool"]
