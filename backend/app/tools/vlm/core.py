"""What every capability of the vision-language model core shares.

Visual question answering, captioning with region grounding and change-VQA
all read a rendered picture of the scene with the same model, so they share
one switch, one reason for being off, and one way of telling the model what
it is looking at. Keeping that here means the three cannot disagree about
whether the model is available or about how a scene is described to it.
"""

from __future__ import annotations

from typing import Any

from app.config.settings import get_settings
from app.tools.base import RemoteSensingTool, ToolExecutionError
from app.tools.raster.inspection import find_acquisition_date
from app.tools.raster.model import RasterDataset
from app.tools.raster.render import Preview, describe_footprint

MAX_QUESTION_LENGTH = 500

NOTICE = (
    "This answer is a vision-language model's reading of a rendered picture of "
    "the scene, not a measurement."
)


def vlm_unavailable_reason() -> str | None:
    """Why the VLM core cannot run, phrased for an operator; ``None`` if it can."""
    settings = get_settings()
    if settings.vqa_available:
        return None
    if settings.vqa_provider not in {"hosted", "ollama"}:
        return (
            f"SATQUERY_VQA_PROVIDER must be 'hosted' or 'ollama', not "
            f"'{settings.vqa_provider}'."
        )
    missing = []
    if not settings.vqa_enabled:
        missing.append("SATQUERY_VQA_ENABLED=true")
    if settings.vqa_uses_agent_endpoint and not settings.resolved_vqa_api_key:
        missing.append("SATQUERY_AGENT_API_KEY")
    what = (
        "runs a vision model on this machine"
        if settings.vqa_is_local
        else "sends a rendered preview of the image to a hosted vision-language model"
    )
    return (
        f"The vision-language model core {what}, so it stays switched off until "
        f"an operator enables it. Set {' and '.join(missing)} to switch it on."
    )


class VisionTool(RemoteSensingTool):
    """A capability answered by the vision-language model core."""

    def available(self) -> bool:
        return get_settings().vqa_available

    def unavailable_reason(self) -> str | None:
        return vlm_unavailable_reason()

    def require_available(self) -> None:
        if not self.available():
            raise ToolExecutionError(vlm_unavailable_reason() or "The vision model is unavailable.")


def question_from(parameters: dict[str, Any]) -> str:
    """The user's question, checked and bounded."""
    question = parameters.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ToolExecutionError("A question is needed for the vision model to answer.")
    return question.strip()[:MAX_QUESTION_LENGTH]


def describe_scene(dataset: RasterDataset, preview: Preview, name: str = "The image") -> str:
    """Tell the model what it is looking at, so it does not misread the picture.

    A false-colour forest is not a fire, radar is not a photograph, and a 10 m
    pixel cannot show a car; each of those is stated rather than left for the
    model to guess.
    """
    acquired = find_acquisition_date(dataset)
    lines = [
        f"- {name} is {preview.description}.",
        f"- Sensor: {dataset.metadata.get('sensor') or 'unknown'}. "
        f"Acquisition date: {acquired.isoformat() if acquired else 'unknown'}.",
    ]
    footprint = describe_footprint(dataset, preview)
    if footprint:
        width_km, height_km = footprint["footprint_km"]
        lines.append(
            f"- It covers about {width_km:.1f} x {height_km:.1f} km; each picture "
            f"pixel is about {footprint['preview_pixel_metres'][0]:.0f} m on the "
            "ground, so smaller objects cannot be seen."
        )
    return "\n".join(lines)


__all__ = [
    "NOTICE",
    "VisionTool",
    "describe_scene",
    "question_from",
    "vlm_unavailable_reason",
]
