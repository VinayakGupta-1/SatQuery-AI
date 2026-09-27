"""Bi-temporal change question answering: measured first, then described.

"What changed between these two dates?" wants two things a single engine
cannot give: how much changed and where, which only arithmetic can say
reliably, and what the change *is* -- a new road, a drained field, a flooded
village -- which needs something that can look at the pictures.

So this capability runs both, in sequence:

1. deterministic change detection measures the change (index or SAR
   log-ratio differencing, thresholded) and locates it;
2. both dates are rendered on one shared stretch, so a brighter pixel is
   brighter on the ground rather than in the display;
3. the vision-language model answers the question with both pictures *and*
   the measurements in its prompt, instructed to treat the numbers as correct.

The measured change map is returned alongside the answer, so the reader can
check the model's description against the measurement it was given.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import StepLog, ToolExecutionError, ToolOutput, ToolRequest
from app.tools.change.alignment import order_by_acquisition
from app.tools.change.bitemporal import BiTemporalChangeDetectionTool
from app.tools.raster.aoi import open_for_analysis
from app.tools.raster.io import backend_report
from app.tools.raster.render import render_pair, write_preview
from app.tools.vlm.client import VisionLanguageModel
from app.tools.vlm.core import NOTICE, VisionTool, describe_scene, question_from

MAX_ANSWER_TOKENS = 500

#: The parameters the measurement step understands.
MEASUREMENT_PARAMETERS = {"index", "threshold", "write_raster", "aoi_bbox", "aoi_crs", "aoi_region"}

PROMPT = """You are a remote-sensing analyst answering a question about how one place changed between two dates.

The first picture is the earlier date:
{earlier}

The second picture is the later date:
{later}

Both pictures use the same brightness scale, so a difference in brightness between them is a difference on the ground.

Measured by deterministic change detection -- treat these numbers as correct and do not contradict or re-estimate them:
{evidence}

Answer the question by describing what the pictures show, consistent with the measurements. If the pictures cannot answer it, say so plainly. Do not invent place names, dates or numbers beyond those given. Answer in at most 150 words.

Question: {question}"""


def _area_text(entry: dict[str, Any]) -> str:
    area = entry.get("area_square_units")
    if not area:
        return ""
    if area >= 1_000_000:
        return f" ({area / 1_000_000:,.2f} km2)"
    return f" ({area / 10_000:,.1f} ha)"


def summarise_measurement(measured: ToolOutput) -> str:
    """The measured change, as lines a model can quote but not recompute."""
    data, statistics = measured.data, measured.statistics
    classes = data.get("classes") or {}
    decrease, increase = classes.get("decrease") or {}, classes.get("increase") or {}
    lines = [
        f"- Method: {data.get('formula')}, with a {data.get('threshold_description')}.",
        f"- {statistics.get('changed_fraction', 0.0):.1%} of the comparable area changed: "
        f"{decrease.get('fraction', 0.0):.1%}{_area_text(decrease)} shows "
        f"{data.get('decrease_means', 'a decrease')}, and {increase.get('fraction', 0.0):.1%}"
        f"{_area_text(increase)} shows {data.get('increase_means', 'an increase')}.",
    ]
    for label, meaning in (("decrease", data.get("decrease_means")), ("increase", data.get("increase_means"))):
        where = (data.get("class_locations") or {}).get(label)
        if where and not where.get("widespread") and (classes.get(label) or {}).get("pixels"):
            lines.append(f"- The {meaning} is centred on the {where['sector']} of the scene.")
    if data.get("earlier_date") and data.get("later_date"):
        lines.append(f"- Dates: {data['earlier_date']} (earlier) and {data['later_date']} (later).")
    return "\n".join(lines)


class ChangeVQATool(VisionTool):
    """Answers a question about change, grounded in measured change."""

    tool_id = "change_vqa"
    result_type = "change_vqa"

    def preflight(self, request: ToolRequest) -> None:
        question_from(request.parameters)

    def execute(self, request: ToolRequest) -> ToolOutput:
        self.require_available()
        question = question_from(request.parameters)
        if len(request.input_references) != 2:
            raise ToolExecutionError(
                f"Change questions need exactly two images, but {len(request.input_references)} were supplied."
            )
        log = StepLog()
        model = VisionLanguageModel()

        with log.step("measure_change", "deterministic change detection"):
            measured = BiTemporalChangeDetectionTool().execute(
                ToolRequest(
                    tool_id="change_detection",
                    input_references=request.input_references,
                    parameters={
                        key: value for key, value in request.parameters.items()
                        if key in MEASUREMENT_PARAMETERS
                    },
                    output_directory=request.output_directory,
                )
            )

        with log.step("render", "both dates on one shared stretch"):
            first, _ = open_for_analysis(request.input_references[0], request.parameters)
            second, _ = open_for_analysis(request.input_references[1], request.parameters)
            earlier, later, _ = order_by_acquisition(first, second)
            before, after = render_pair(earlier, later)

        prompt = PROMPT.format(
            earlier=describe_scene(earlier, before, "The earlier picture"),
            later=describe_scene(later, after, "The later picture"),
            evidence=summarise_measurement(measured),
            question=question,
        )
        with log.step("ask_model", model.identity):
            answer = model.complete(prompt, [before.png, after.png], max_tokens=MAX_ANSWER_TOKENS)

        artifacts = list(measured.artifacts)
        if request.parameters.get("write_raster", True):
            artifacts += [
                write_preview(request, earlier, earlier.path or "earlier", "earlier_preview", preview=before),
                write_preview(request, later, later.path or "later", "later_preview", preview=after),
            ]

        data = measured.data
        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "question": question,
                "answer": answer,
                "model": model.model,
                "provider": model.provider,
                "measured": {
                    key: data.get(key)
                    for key in (
                        "index", "method", "formula", "threshold_description",
                        "increase_means", "decrease_means", "earlier_date", "later_date",
                        "class_locations",
                    )
                },
                "classes": data.get("classes") or {},
                "rendering_description": f"{before.description} (both dates on one stretch)",
                "preview_size": [before.width, before.height],
                "notice": NOTICE + " The change figures it was given were measured.",
            },
            statistics=measured.statistics,
            artifacts=artifacts,
            metadata={
                **measured.metadata,
                "vlm": model.identity,
                "steps": log.steps + [
                    {**step, "name": f"measure_change.{step['name']}"}
                    for step in measured.metadata.get("steps", [])
                ],
                **backend_report(),
            },
        )


__all__ = ["ChangeVQATool", "summarise_measurement"]
