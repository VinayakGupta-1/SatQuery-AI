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

from app.schemas.results import Evidence

# ============================================================
# UNITS
# ============================================================
#: EPSG codes in this range are geographic (degrees), not projected (metres).
GEOGRAPHIC_EPSG_RANGE = (4000, 4999)


def is_projected_crs(crs: str | None) -> bool:
    """Return True when ``crs`` measures distance in linear units.

    Areas may only be converted to hectares or square kilometres for a
    projected CRS. In a geographic CRS the raster's "pixel area" is in square
    degrees, whose ground size varies with latitude, so converting it would
    produce a confidently wrong number.
    """
    if not crs or not crs.upper().startswith("EPSG:"):
        return False
    try:
        code = int(crs.split(":", 1)[1])
    except ValueError:
        return False
    return not (GEOGRAPHIC_EPSG_RANGE[0] <= code <= GEOGRAPHIC_EPSG_RANGE[1])


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


# ============================================================
# NARRATOR REGISTRY
# ============================================================
_NARRATORS: list[ResultNarrator] = [
    RasterIndexNarrator(),
    ChangeMapNarrator(),
]

NARRATORS: dict[str, ResultNarrator] = {
    narrator.result_type: narrator for narrator in _NARRATORS
}

DEFAULT_NARRATOR = ResultNarrator()


def get_narrator(result_type: str | None) -> ResultNarrator:
    """Return the narrator for ``result_type``, falling back to the generic one."""
    return NARRATORS.get(result_type or "", DEFAULT_NARRATOR)
