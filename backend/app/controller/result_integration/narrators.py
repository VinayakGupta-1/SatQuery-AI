"""Deterministic narration of tool output into plain language.

Every sentence a narrator produces is derived arithmetically from numbers the
tool actually reported. Nothing here interprets, embellishes or infers beyond
the statistics in hand -- when a value is absent, the sentence is omitted
rather than filled in. That property is what makes this layer safe to keep
when an LLM is eventually added above it: the narration stays checkable.

Narrators are keyed by ``result_type``, so a new tool adds a narrator rather
than a branch inside the integrator.
"""

from __future__ import annotations

from typing import Any

from app.schemas.results import Evidence, Finding
from app.tools.raster.locate import sector
from app.tools.raster.model import is_projected_crs


# ============================================================
# UNITS
# ============================================================
def format_area(square_metres: float) -> str:
    """Render an area in the unit that keeps it readable."""
    if square_metres >= 1_000_000:
        return f"{square_metres / 1_000_000:,.2f} km2"
    if square_metres >= 10_000:
        return f"{square_metres / 10_000:,.2f} ha"
    return f"{square_metres:,.0f} m2"


def humanise(label: str) -> str:
    """Turn a snake_case class label into readable words."""
    return label.replace("_", " ")


def format_lonlat(lonlat: list[float] | tuple[float, float]) -> str:
    """``[79.08, 21.14]`` -> ``21.1400° N, 79.0800° E``."""
    lon, lat = lonlat
    return (
        f"{abs(lat):.4f}° {'N' if lat >= 0 else 'S'}, "
        f"{abs(lon):.4f}° {'E' if lon >= 0 else 'W'}"
    )


def describe_location(where: dict[str, Any] | None) -> str:
    """Where a class or object lies, in words."""
    if not where:
        return ""
    if where.get("widespread"):
        text = "spread across the scene"
    elif where.get("sector") == "centre":
        text = "centred on the middle of the scene"
    else:
        text = f"centred on the {where.get('sector')} of the scene"
    if where.get("centroid_lonlat"):
        text += f", around {format_lonlat(where['centroid_lonlat'])}"
    return text


def _location(where: dict[str, Any] | None) -> dict[str, Any] | None:
    if not where:
        return None
    return {
        key: where[key]
        for key in ("sector", "widespread", "centroid_lonlat", "centroid_pixel")
        if key in where
    }


def class_findings(
    output: dict[str, Any],
    skip: tuple[str, ...] = (),
    names: dict[str, str] | None = None,
    limit: int = 4,
    min_fraction: float = 0.01,
) -> list[Finding]:
    """One finding per notable class: how much of it, and where it lies."""
    data = output.get("data") or {}
    classes = data.get("classes") or {}
    locations = data.get("class_locations") or {}
    crs = _crs_of(output)
    ranked = sorted(
        (
            (label, entry)
            for label, entry in classes.items()
            if label not in skip and entry.get("pixels") and entry.get("fraction", 0) >= min_fraction
        ),
        key=lambda item: -item[1]["fraction"],
    )
    findings = []
    for label, entry in ranked[:limit]:
        amount = f"{entry['fraction']:.1%} of the observed area"
        area = entry.get("area_square_units")
        if area is not None and is_projected_crs(crs):
            amount = f"{format_area(area)}, {amount}"
        where = locations.get(label)
        detail = f"{amount}; {describe_location(where)}." if where else f"{amount}."
        title = (names or {}).get(label) or humanise(label).capitalize()
        findings.append(Finding(title=title, detail=detail, location=_location(where)))
    return findings


# ============================================================
# NARRATORS
# ============================================================
class ResultNarrator:
    """Base narrator, used for any result type without a specific one."""

    result_type = "generic"

    def answer(self, output: dict[str, Any]) -> str:
        statistics = output.get("statistics") or {}
        parts = [
            f"The '{output.get('tool_id', 'tool')}' tool completed and returned a "
            f"{humanise(output.get('result_type', 'generic'))} result."
        ]
        valid = statistics.get("valid_pixels")
        total = statistics.get("total_pixels")
        if valid is not None and total:
            parts.append(f"{valid:,} of {total:,} pixels were computable.")
        return " ".join(parts)

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        """Describe where the result came from.

        ``source`` is a stable logical label, never a filesystem path. Evidence
        is returned over the API, and a server path would both leak deployment
        detail and mean nothing to the reader. The path itself stays available
        in the execution metadata for auditing.
        """
        evidence: list[Evidence] = []
        source = (output.get("metadata") or {}).get("source") or {}
        if source:
            evidence.append(
                Evidence(
                    source="source_raster",
                    description=(
                        f"Source raster: {source.get('width')}x{source.get('height')} "
                        f"pixels, bands {source.get('band_names')}, "
                        f"CRS {source.get('crs') or 'unspecified'}."
                    ),
                )
            )
        for artifact in output.get("artifacts") or []:
            evidence.append(
                Evidence(
                    source=artifact.get("artifact_id", "artifact"),
                    description=artifact.get("description", ""),
                )
            )
        return evidence

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        """The answer broken into grounded parts. Class maps by default."""
        return class_findings(output)


class RasterIndexNarrator(ResultNarrator):
    """Narrates the output of NDVI, NDWI, NDBI and other index tools."""

    result_type = "raster_index"

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        statistics = output.get("statistics") or {}
        index = data.get("index", "The index")

        sentences: list[str] = []

        mean = statistics.get("mean")
        if mean is None:
            return (
                f"{index} could not be computed anywhere in this scene: none of the "
                f"{statistics.get('total_pixels', 0):,} pixels had valid values in "
                "both required bands."
            )

        sentences.append(
            f"Mean {index} is {mean:.3f}, ranging from "
            f"{statistics['minimum']:.3f} to {statistics['maximum']:.3f}."
        )

        sentences.append(self._coverage_sentence(statistics))

        dominant = self._dominant_class(data, statistics, output)
        if dominant:
            sentences.append(dominant)

        sentences.append(f"Computed as {data.get('formula', 'a normalised difference')}.")
        return " ".join(sentences)

    @staticmethod
    def _coverage_sentence(statistics: dict[str, Any]) -> str:
        valid = statistics.get("valid_pixels", 0)
        total = statistics.get("total_pixels", 0)
        fraction = statistics.get("valid_fraction", 0.0)
        if fraction >= 1.0:
            return f"All {total:,} pixels were computable."
        return (
            f"{valid:,} of {total:,} pixels were computable ({fraction:.1%}); the "
            "remainder were nodata or had an undefined denominator."
        )

    def _dominant_class(
        self,
        data: dict[str, Any],
        statistics: dict[str, Any],
        output: dict[str, Any],
    ) -> str | None:
        classes = data.get("classes") or {}
        if not classes:
            return None

        label, summary = max(classes.items(), key=lambda item: item[1]["pixels"])
        if summary["pixels"] == 0:
            return None

        sentence = (
            f"The scene is predominantly {humanise(label)}, covering "
            f"{summary['fraction']:.1%} of the valid pixels"
        )

        crs = ((output.get("metadata") or {}).get("source") or {}).get("crs")
        area = summary.get("area_square_units")
        if area is not None and is_projected_crs(crs):
            sentence += f" ({format_area(area)})"
        return sentence + "."

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        evidence = super().evidence(output)
        data = output.get("data") or {}
        statistics = output.get("statistics") or {}

        if data.get("formula"):
            evidence.append(
                Evidence(
                    source="formula",
                    description=(
                        f"{data.get('index', 'Index')} = {data['formula']}, computed "
                        f"pixel-wise on the source grid."
                    ),
                )
            )
        if data.get("interpretation"):
            evidence.append(
                Evidence(source="interpretation", description=data["interpretation"])
            )
        if "valid_fraction" in statistics:
            evidence.append(
                Evidence(
                    source="coverage",
                    description=(
                        f"{statistics.get('valid_pixels', 0):,} of "
                        f"{statistics.get('total_pixels', 0):,} pixels contributed to "
                        "these statistics."
                    ),
                    confidence=statistics["valid_fraction"],
                )
            )
        return evidence


class ChangeMapNarrator(ResultNarrator):
    """Narrates a bi-temporal change detection result."""

    result_type = "change_map"

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        data = output.get("data") or {}
        return class_findings(
            output,
            skip=("stable",),
            names={
                "decrease": str(data.get("decrease_means", "decrease")).capitalize(),
                "increase": str(data.get("increase_means", "increase")).capitalize(),
            },
            min_fraction=0.0,
        )

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        statistics = output.get("statistics") or {}
        classes = data.get("classes") or {}
        index = data.get("index", "the index")

        valid = statistics.get("valid_pixels", 0)
        if not valid:
            return (
                "No change could be assessed: no pixel had a valid "
                f"{index} value on both dates."
            )

        changed = statistics.get("changed_pixels", 0)
        sentences = [
            f"{changed:,} of {valid:,} comparable pixels changed "
            f"({statistics.get('changed_fraction', 0.0):.1%}), using a "
            f"{data.get('threshold_description', 'threshold')} on the "
            f"{index} difference."
        ]

        sentences.append(self._direction_sentence(data, classes, output))
        sentences.append(self._period_sentence(data))
        return " ".join(part for part in sentences if part)

    def _direction_sentence(
        self,
        data: dict[str, Any],
        classes: dict[str, Any],
        output: dict[str, Any],
    ) -> str:
        increase = classes.get("increase", {})
        decrease = classes.get("decrease", {})
        crs = ((output.get("metadata") or {}).get("earlier") or {}).get("crs")

        def describe(entry: dict[str, Any], meaning: str) -> str:
            text = f"{entry.get('fraction', 0.0):.1%} shows {meaning}"
            area = entry.get("area_square_units")
            if area is not None and is_projected_crs(crs) and area > 0:
                text += f" ({format_area(area)})"
            return text

        parts = []
        if increase.get("pixels"):
            parts.append(describe(increase, data.get("increase_means", "an increase")))
        if decrease.get("pixels"):
            parts.append(describe(decrease, data.get("decrease_means", "a decrease")))

        if not parts:
            return "No pixel exceeded the threshold in either direction."
        return "Of the comparable area, " + " and ".join(parts) + "."

    @staticmethod
    def _period_sentence(data: dict[str, Any]) -> str:
        earlier, later = data.get("earlier_date"), data.get("later_date")
        if data.get("temporal_order_source") == "acquisition_date" and earlier and later:
            return f"Compared between {earlier} and {later}."
        return (
            "Acquisition dates were not both available, so the images were "
            "compared in the order supplied."
        )

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        evidence: list[Evidence] = []
        data = output.get("data") or {}
        statistics = output.get("statistics") or {}
        metadata = output.get("metadata") or {}

        for role in ("earlier", "later"):
            source = metadata.get(role) or {}
            if source:
                evidence.append(
                    Evidence(
                        source=f"{role}_raster",
                        description=(
                            f"{role.capitalize()} image: "
                            f"{source.get('width')}x{source.get('height')} pixels, "
                            f"CRS {source.get('crs') or 'unspecified'}."
                        ),
                    )
                )

        for artifact in output.get("artifacts") or []:
            evidence.append(
                Evidence(
                    source=artifact.get("artifact_id", "artifact"),
                    description=artifact.get("description", ""),
                )
            )

        if data.get("formula"):
            evidence.append(
                Evidence(
                    source="method",
                    description=(
                        f"{data['formula']}, where {data.get('index_formula', '')} "
                        f"on each date. Change was called where the magnitude "
                        f"exceeded {data.get('threshold', 0):.4f}."
                    ),
                )
            )
        if data.get("temporal_order_source") == "input_order":
            evidence.append(
                Evidence(
                    source="temporal_order",
                    description=(
                        "Acquisition dates were not present in both rasters, so the "
                        "input order was assumed to run earliest first. The sign of "
                        "the reported change depends on that assumption."
                    ),
                )
            )
        if "valid_fraction" in statistics:
            evidence.append(
                Evidence(
                    source="coverage",
                    description=(
                        f"{statistics.get('valid_pixels', 0):,} of "
                        f"{statistics.get('total_pixels', 0):,} pixels were valid on "
                        "both dates and could be compared."
                    ),
                    confidence=statistics["valid_fraction"],
                )
            )
        return evidence


def _crs_of(output: dict[str, Any]) -> str | None:
    metadata = output.get("metadata") or {}
    return (metadata.get("source") or metadata.get("earlier") or {}).get("crs")


def _with_area(text: str, area: float | None, crs: str | None) -> str:
    if area is not None and area > 0 and is_projected_crs(crs):
        return f"{text} ({format_area(area)})"
    return text


def _coverage_evidence(statistics: dict[str, Any], what: str) -> list[Evidence]:
    if "valid_fraction" not in statistics:
        return []
    return [
        Evidence(
            source="coverage",
            description=(
                f"{statistics.get('valid_pixels', 0):,} of "
                f"{statistics.get('total_pixels', 0):,} pixels could be {what}."
            ),
            confidence=statistics["valid_fraction"],
        )
    ]


class LandCoverNarrator(ResultNarrator):
    """Narrates a land-cover classification."""

    result_type = "land_cover"

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        statistics = output.get("statistics") or {}
        classes = data.get("classes") or {}
        crs = _crs_of(output)

        present = sorted(
            ((label, entry) for label, entry in classes.items() if entry.get("pixels")),
            key=lambda item: -item[1]["pixels"],
        )
        if not present:
            return (
                "No pixel could be classified: none had valid values in every "
                "band the rules need."
            )

        parts = [
            _with_area(f"{humanise(label)} {entry['fraction']:.1%}", entry.get("area_square_units"), crs)
            for label, entry in present
        ]
        top_label, top = present[0]
        lead = (
            f"The scene is mostly {humanise(top_label)}."
            if top["fraction"] >= 0.5
            else f"{humanise(top_label).capitalize()} is the largest class."
        )
        sentences = [
            f"{lead} Across the {statistics.get('valid_pixels', 0):,} classified "
            "pixels: " + ", ".join(parts) + "."
        ]
        if not data.get("swir_available", True):
            sentences.append(
                "Without a SWIR band, bare ground and built-up land are reported together."
            )
        sentences.append("Classified with transparent NDWI, NDVI and NDBI rules, not a trained model.")
        return " ".join(sentences)

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        evidence = super().evidence(output)
        data = output.get("data") or {}
        if data.get("rules"):
            evidence.append(
                Evidence(
                    source="method",
                    description="Rules, applied in order: " + "; ".join(data["rules"]) + ".",
                )
            )
        if data.get("interpretation"):
            evidence.append(Evidence(source="interpretation", description=data["interpretation"]))
        return evidence + _coverage_evidence(output.get("statistics") or {}, "classified")


class SARFloodNarrator(ResultNarrator):
    """Narrates a flood map: new water against a dry-season reference."""

    result_type = "sar_flood_map"

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        return class_findings(
            output,
            skip=("dry_land",),
            names={
                "flooded": "Flooded (new water)",
                "permanent_water": "Permanent water, not counted as flood",
                "receded_water": "Water in the reference, dry now",
            },
            min_fraction=0.0,
        )

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        statistics = output.get("statistics") or {}
        classes = data.get("classes") or {}
        crs = _crs_of(output)
        if not statistics.get("valid_pixels"):
            return "No flooding could be mapped: no pixel was observed on both dates."

        flooded = classes.get("flooded") or {}
        permanent = classes.get("permanent_water") or {}
        receded = classes.get("receded_water") or {}
        event, reference = data.get("event_date", "the flood date"), data.get("reference_date", "the reference")
        sentences = [
            _with_area(
                f"Flooding covers {flooded.get('fraction', 0.0):.1%} of the observed area",
                flooded.get("area_square_units"),
                crs,
            )
            + f": open water on {event} where the dry-season reference of {reference} was dry."
        ]
        if permanent.get("pixels"):
            sentences.append(
                _with_area(
                    f"A further {permanent.get('fraction', 0.0):.1%}",
                    permanent.get("area_square_units"),
                    crs,
                )
                + " was water on both dates -- rivers, lakes or sea -- and is not counted as flood."
            )
        if receded.get("pixels"):
            sentences.append(
                f"{receded.get('fraction', 0.0):.1%} that was water in the reference is dry now."
            )
        sentences.append(
            f"Both dates were mapped with one {data.get('threshold_description', 'threshold')} "
            f"on {data.get('polarisation', 'radar')} backscatter; radar sees through cloud."
        )
        return " ".join(sentences)


class SARWaterNarrator(ResultNarrator):
    """Narrates a SAR water map."""

    result_type = "sar_water_map"

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        return class_findings(output, skip=("non_water",), names={"water": "Open water"}, min_fraction=0.0)

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        statistics = output.get("statistics") or {}
        water = (data.get("classes") or {}).get("water") or {}
        polarisation = data.get("polarisation", "backscatter")

        if not statistics.get("valid_pixels"):
            return "No water could be mapped: the SAR band has no valid pixels."

        sentences = [
            _with_area(
                f"Open water covers {water.get('fraction', 0.0):.1%} of the observed scene",
                water.get("area_square_units"),
                _crs_of(output),
            )
            + f", where {polarisation} backscatter falls below the "
            f"{data.get('threshold_description', 'threshold')}."
        ]
        median = statistics.get("median")
        if median is not None:
            sentences.append(f"Median {polarisation} backscatter is {median:.1f} dB.")
        sentences.append("Radar sees through cloud, so the map is not limited by cloud cover.")
        return " ".join(sentences)

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        evidence = super().evidence(output)
        data = output.get("data") or {}
        evidence.append(
            Evidence(
                source="method",
                description=(
                    f"{data.get('polarisation', 'Backscatter')} read as "
                    f"{data.get('input_units', 'calibrated')} "
                    f"({data.get('input_units_source', 'detected')}), converted to dB, "
                    f"speckle filter: {data.get('speckle_filter', 'none')}; water where "
                    f"the value is below the {data.get('threshold_description', 'threshold')}."
                ),
            )
        )
        if data.get("interpretation"):
            evidence.append(Evidence(source="interpretation", description=data["interpretation"]))
        return evidence + _coverage_evidence(output.get("statistics") or {}, "assessed")


class DetectionsNarrator(ResultNarrator):
    """Narrates region-based object detection."""

    result_type = "detections"

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        data = output.get("data") or {}
        source = (output.get("metadata") or {}).get("source") or {}
        width, height = source.get("width") or 0, source.get("height") or 0
        crs = _crs_of(output)
        findings = []
        for detection in (data.get("detections") or [])[:3]:
            col, row = detection.get("centroid_pixel", [0, 0])
            where = {
                "sector": sector((col + 0.5) / width, (row + 0.5) / height) if width and height else "centre",
                "centroid_pixel": detection.get("centroid_pixel"),
            }
            if detection.get("centroid_lonlat"):
                where["centroid_lonlat"] = detection["centroid_lonlat"]
            area = detection.get("area_square_units")
            size = (
                format_area(area) if area is not None and is_projected_crs(crs)
                else f"{detection.get('pixels', 0):,} pixels"
            )
            findings.append(
                Finding(
                    title=f"{humanise(detection.get('label', 'object')).capitalize()} #{detection.get('id')}",
                    detail=f"{size}; {describe_location(where)}.",
                    location=_location(where),
                )
            )
        return findings

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        counts = data.get("counts") or {}
        detections = data.get("detections") or []
        total = data.get("detections_total", len(detections))
        crs = _crs_of(output)

        sentences: list[str] = []
        if not total:
            searched = ", ".join(_plural(label, 2) for label in counts) or "objects"
            sentences.append(
                f"No {searched} of at least {data.get('min_area_pixels', 1)} pixels were found."
            )
        else:
            parts = []
            for label, count in sorted(counts.items(), key=lambda item: -item[1]):
                if not count:
                    continue
                text = f"{count} {_plural(label, count)}"
                # Detections are ordered by size, so the first of a label is
                # its largest.
                largest = next((d for d in detections if d.get("label") == label), None)
                area = largest.get("area_square_units") if largest else None
                if area is not None and area > 0 and is_projected_crs(crs):
                    text += f" ({'largest ' if count > 1 else ''}{format_area(area)})"
                parts.append(text)
            sentences.append(f"Found {total} discrete object{'s' if total != 1 else ''}: " + "; ".join(parts) + ".")
            sentences.append(
                f"Regions smaller than {data.get('min_area_pixels', 1)} pixels were ignored."
            )
        unresolvable = data.get("unresolvable_targets") or []
        if unresolvable:
            sentences.append(
                f"{', '.join(unresolvable).capitalize()} could not be searched for: "
                "individual objects that small need sub-metre imagery and a trained detector."
            )
        sentences.append(
            "Each object is a connected patch of one land-cover class, not the output of a "
            "trained detector."
        )
        return " ".join(sentences)

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        evidence = super().evidence(output)
        data = output.get("data") or {}
        evidence.append(
            Evidence(
                source="method",
                description=(
                    f"Connected regions ({data.get('connectivity', 8)}-connectivity) of the "
                    "land-cover classes, from the rules: "
                    + "; ".join(data.get("classification_rules") or [])
                    + "."
                ),
            )
        )
        if data.get("detections_total", 0) > data.get("detections_returned", 0):
            evidence.append(
                Evidence(
                    source="truncation",
                    description=(
                        f"The {data['detections_returned']} largest of "
                        f"{data['detections_total']} objects are listed; all are in the "
                        "object raster."
                    ),
                )
            )
        return evidence + _coverage_evidence(output.get("statistics") or {}, "classified")


class VQANarrator(ResultNarrator):
    """Passes a vision model's answer through, labelled as such."""

    result_type = "vqa_answer"

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        # The answer is the finding; nothing in it was measured to break out.
        return []

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        return f"{data.get('answer', '').strip()}\n\n{data.get('notice', '')}".strip()

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        evidence = super().evidence(output)
        data = output.get("data") or {}
        evidence.append(
            Evidence(
                source="vision_model",
                description=(
                    f"Answered by {data.get('model', 'a hosted vision model')} from a "
                    f"{'x'.join(str(v) for v in data.get('preview_size', []))} preview: "
                    f"{data.get('rendering_description', 'a rendering of the scene')}."
                ),
            )
        )
        return evidence


class FusionNarrator(ResultNarrator):
    """Narrates an optical + SAR water fusion."""

    result_type = "fusion_water_map"

    NAMES = {
        "water_both": "Water seen by both sensors",
        "water_radar_only": "Water seen only by radar",
        "water_optical_only": "Water seen only in the optical image",
        "water_under_cloud": "Water under cloud, seen by radar",
    }

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        statistics = output.get("statistics") or {}
        classes = data.get("classes") or {}
        if not statistics.get("valid_pixels"):
            return "Neither image had a usable pixel, so no water could be mapped."

        def part(label: str) -> float:
            return (classes.get(label) or {}).get("fraction", 0.0)

        water_area = sum(
            (classes.get(label) or {}).get("area_square_units") or 0.0 for label in self.NAMES
        )
        lead = f"Fusing the optical and radar images, open water covers {statistics.get('water_fraction', 0.0):.1%} of the scene"
        if water_area and is_projected_crs(_crs_of(output)):
            lead += f" ({format_area(water_area)})"
        sentences = [lead + "."]
        sentences.append(
            f"Both sensors saw {part('water_both'):.1%} of the scene as water; radar alone "
            f"found {part('water_under_cloud'):.1%} more under cloud, where the optical image "
            "could not see."
            + (
                f" A further {part('water_radar_only'):.1%} is water to radar but land to the "
                "optical image."
                if part("water_radar_only") >= 0.001 else ""
            )
        )
        if statistics.get("kappa") is not None:
            sentences.append(
                f"Where both could observe, they agree on {statistics.get('observed_agreement', 0.0):.1%} "
                f"of pixels (Cohen's kappa {statistics['kappa']:.2f})."
            )
        if not data.get("cloud_mask"):
            sentences.append(
                "The optical image carried no cloud mask, so cloud could not be told apart from land."
            )
        return " ".join(sentences)

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        evidence = super().evidence(output)
        data = output.get("data") or {}
        evidence.append(
            Evidence(
                source="method",
                description=(
                    f"Optical water: {data.get('optical_rule')} (cloud mask: "
                    f"{data.get('cloud_mask') or 'none'}). Radar water: {data.get('radar_rule')}, "
                    f"speckle filter {data.get('speckle_filter')}."
                ),
            )
        )
        if data.get("days_apart") is not None:
            evidence.append(
                Evidence(
                    source="timing",
                    description=(
                        f"Optical {data.get('optical_date')}, radar {data.get('radar_date')}: "
                        f"{data['days_apart']} day(s) apart."
                    ),
                )
            )
        if data.get("interpretation"):
            evidence.append(Evidence(source="interpretation", description=data["interpretation"]))
        return evidence + _coverage_evidence(output.get("statistics") or {}, "observed by either sensor")

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        findings = class_findings(output, skip=("land",), names=self.NAMES, min_fraction=0.0)
        statistics = output.get("statistics") or {}
        if statistics.get("kappa") is not None:
            findings.append(
                Finding(
                    title="Sensor agreement",
                    detail=(
                        f"Cohen's kappa {statistics['kappa']:.2f} over "
                        f"{statistics.get('pixels_seen_by_both', 0):,} pixels both sensors observed."
                    ),
                )
            )
        return findings


class CaptionNarrator(ResultNarrator):
    """Passes a model's caption through, with its grounded regions as findings."""

    result_type = "caption"

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        return f"{data.get('caption', '').strip()}\n\n{data.get('notice', '')}".strip()

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        evidence = super().evidence(output)
        data = output.get("data") or {}
        evidence.append(
            Evidence(
                source="vision_model",
                description=(
                    f"Captioned by {data.get('model', 'a vision model')} from "
                    f"{data.get('rendering_description', 'a rendering of the scene')}; "
                    f"{len(data.get('regions') or [])} region(s) grounded."
                ),
            )
        )
        for note in data.get("notes") or []:
            evidence.append(Evidence(source="grounding", description=note))
        return evidence

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        findings = []
        for region in (output.get("data") or {}).get("regions") or []:
            where = {"box_fraction": region.get("box_fraction")}
            detail = "Proposed by the model"
            if region.get("centre_lonlat"):
                where["centroid_lonlat"] = region["centre_lonlat"]
                detail += f", around {format_lonlat(region['centre_lonlat'])}"
            findings.append(Finding(title=region.get("label", "region"), detail=detail + ".", location=where))
        return findings


class ChangeVQANarrator(ResultNarrator):
    """A model's answer about change, with the measured change as findings."""

    result_type = "change_vqa"

    def answer(self, output: dict[str, Any]) -> str:
        data = output.get("data") or {}
        return f"{data.get('answer', '').strip()}\n\n{data.get('notice', '')}".strip()

    def evidence(self, output: dict[str, Any]) -> list[Evidence]:
        data = output.get("data") or {}
        measured = data.get("measured") or {}
        statistics = output.get("statistics") or {}
        return [
            Evidence(
                source="measured_change",
                description=(
                    f"Measured before answering: {statistics.get('changed_fraction', 0.0):.1%} of "
                    f"comparable pixels changed ({measured.get('formula')}, "
                    f"{measured.get('threshold_description')})."
                ),
            ),
            Evidence(
                source="vision_model",
                description=(
                    f"Answered by {data.get('model', 'a vision model')} from both dates, "
                    f"{data.get('rendering_description', '')}."
                ),
            ),
        ] + _coverage_evidence(statistics, "compared")

    def findings(self, output: dict[str, Any]) -> list[Finding]:
        data = output.get("data") or {}
        measured = data.get("measured") or {}
        return class_findings(
            {**output, "data": {"classes": data.get("classes"), "class_locations": measured.get("class_locations")}},
            skip=("stable",),
            names={
                "decrease": f"Measured: {measured.get('decrease_means', 'decrease')}",
                "increase": f"Measured: {measured.get('increase_means', 'increase')}",
            },
            min_fraction=0.0,
        )


def _plural(label: str, count: int) -> str:
    """``water_body`` -> ``water bodies``; ``vegetation_patch`` -> ``vegetation patches``."""
    words = humanise(label)
    if count == 1:
        return words
    if words.endswith("y") and words[-2:-1] not in "aeiou":
        return words[:-1] + "ies"
    if words.endswith(("s", "x", "ch", "sh")):
        return words + "es"
    return words + "s"


# ============================================================
# NARRATOR REGISTRY
# ============================================================
_NARRATORS: list[ResultNarrator] = [
    RasterIndexNarrator(),
    ChangeMapNarrator(),
    LandCoverNarrator(),
    SARWaterNarrator(),
    SARFloodNarrator(),
    DetectionsNarrator(),
    VQANarrator(),
    FusionNarrator(),
    CaptionNarrator(),
    ChangeVQANarrator(),
]

NARRATORS: dict[str, ResultNarrator] = {
    narrator.result_type: narrator for narrator in _NARRATORS
}

DEFAULT_NARRATOR = ResultNarrator()


def get_narrator(result_type: str | None) -> ResultNarrator:
    """Return the narrator for ``result_type``, falling back to the generic one."""
    return NARRATORS.get(result_type or "", DEFAULT_NARRATOR)
