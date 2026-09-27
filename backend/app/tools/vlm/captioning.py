"""Image captioning with region grounding.

The model describes the scene and outlines what its description refers to --
"a river crossing from west to east", "a dense settlement in the south-west"
-- as boxes on the picture. Each box is then placed back on the raster: pixel
coordinates always, map coordinates and longitude/latitude when the raster is
georeferenced, so a grounded caption lands on the map rather than floating
beside it.

The boxes are the model's proposals. They are validated (inside the picture,
properly ordered, a bounded number of them) but not measured, and the result
says so. A reply that is not the requested JSON degrades to a caption without
regions and a note, rather than failing or inventing boxes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.tools.base import StepLog, ToolExecutionError, ToolOutput, ToolRequest
from app.tools.raster.aoi import open_for_analysis
from app.tools.raster.crs import to_lonlat
from app.tools.raster.io import backend_report
from app.tools.raster.model import RasterDataset
from app.tools.raster.render import render_preview, write_preview
from app.tools.vlm.client import VisionLanguageModel
from app.tools.vlm.core import VisionTool, describe_scene

MAX_REGIONS = 8
MAX_LABEL_LENGTH = 60

PROMPT = """You are a remote-sensing analyst describing a satellite image.

About the image:
{scene}

Reply with one JSON object and nothing else:
{{"caption": "two or three sentences describing what the scene shows",
 "regions": [{{"label": "short name of a visible feature", "box": [x_min, y_min, x_max, y_max]}}]}}

Each "box" gives the feature's extent as fractions of the picture's width and height, from 0 to 1, with (0, 0) at the top-left. List at most {max_regions} regions, only for features that are clearly visible. Use an empty list if none are. Do not invent place names."""

NOTICE = (
    "The caption and the outlined regions are a vision-language model's reading "
    "of the picture. The regions are its proposals, not measured boundaries."
)


def parse_reply(raw: str) -> tuple[str, list[Any], list[str]]:
    """``(caption, raw_regions, notes)`` from whatever the model returned."""
    notes: list[str] = []
    parsed: Any = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        notes.append("The model did not reply in the requested format, so no regions were grounded.")
        return raw.strip(), [], notes
    caption = parsed.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        raise ToolExecutionError("The vision model returned no caption.")
    regions = parsed.get("regions")
    return caption.strip(), regions if isinstance(regions, list) else [], notes


def _fractions(box: Any) -> list[float] | None:
    """A box as fractions of the picture, or ``None`` if it is not usable.

    Fractions are what the prompt asks for. Per-mille coordinates (0-1000),
    a common convention among vision models, are accepted too; anything else
    is rejected rather than guessed at.
    """
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        values = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    top = max(values)
    if top <= 1.0:
        scale = 1.0
    elif top <= 1000.0:
        scale = 1000.0
    else:
        return None
    x0, y0, x1, y1 = (min(max(v / scale, 0.0), 1.0) for v in values)
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def ground_regions(raw_regions: list[Any], dataset: RasterDataset) -> tuple[list[dict[str, Any]], int]:
    """Place each proposed region on the raster. Returns ``(regions, rejected)``."""
    regions: list[dict[str, Any]] = []
    rejected = 0
    transform = dataset.georeference.transform if dataset.georeference.is_georeferenced else None
    for entry in raw_regions[: MAX_REGIONS * 2]:
        if len(regions) >= MAX_REGIONS:
            break
        if not isinstance(entry, dict) or not isinstance(entry.get("label"), str):
            rejected += 1
            continue
        fractions = _fractions(entry.get("box"))
        if fractions is None:
            rejected += 1
            continue
        x0, y0, x1, y1 = fractions
        c0, r0 = int(x0 * dataset.width), int(y0 * dataset.height)
        c1 = max(c0, min(dataset.width - 1, int(x1 * dataset.width) - 1))
        r1 = max(r0, min(dataset.height - 1, int(y1 * dataset.height) - 1))
        region: dict[str, Any] = {
            "label": entry["label"].strip()[:MAX_LABEL_LENGTH],
            "box_fraction": [round(v, 4) for v in fractions],
            "bbox_pixels": [c0, r0, c1, r1],
        }
        if transform is not None:
            origin_x, pixel_w, _, origin_y, _, pixel_h = transform
            xs = (origin_x + c0 * pixel_w, origin_x + (c1 + 1) * pixel_w)
            ys = (origin_y + r0 * pixel_h, origin_y + (r1 + 1) * pixel_h)
            region["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
            centre = to_lonlat(sum(xs) / 2, sum(ys) / 2, dataset.georeference.crs)
            if centre is not None:
                region["centre_lonlat"] = [round(centre[0], 5), round(centre[1], 5)]
        regions.append(region)
    return regions, rejected


class ImageCaptioningTool(VisionTool):
    """Describes a scene and grounds the regions the description names."""

    tool_id = "image_captioning"
    result_type = "caption"

    def execute(self, request: ToolRequest) -> ToolOutput:
        self.require_available()
        path = self.require_single_input(request)
        log = StepLog()
        model = VisionLanguageModel()

        with log.step("open", "read and clip the imagery"):
            dataset, aoi = open_for_analysis(path, request.parameters)
        with log.step("render", "picture for the model"):
            picture = render_preview(dataset)
        with log.step("ask_model", model.identity):
            raw = model.complete(
                PROMPT.format(scene=describe_scene(dataset, picture), max_regions=MAX_REGIONS),
                [picture.png],
                json_mode=True,
                max_tokens=600,
            )
        with log.step("ground_regions", "place proposed boxes on the raster"):
            caption, raw_regions, notes = parse_reply(raw)
            regions, rejected = ground_regions(raw_regions, dataset)
        if rejected:
            notes.append(f"{rejected} proposed region(s) were malformed or outside the picture and were dropped.")

        artifacts = []
        if request.parameters.get("write_raster", True):
            artifacts.append(write_preview(request, dataset, path, "caption_preview", preview=picture))

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "caption": caption,
                "regions": regions,
                "notes": notes,
                "model": model.model,
                "provider": model.provider,
                "rendering": picture.kind,
                "rendering_description": picture.description,
                "preview_size": [picture.width, picture.height],
                "notice": NOTICE,
            },
            artifacts=artifacts,
            metadata={
                "source": dataset.describe(),
                "sensor": dataset.metadata.get("sensor"),
                "aoi": aoi,
                "vlm": model.identity,
                "steps": log.steps,
                **backend_report(),
            },
        )


__all__ = ["ImageCaptioningTool", "ground_regions", "parse_reply"]
