import re
from typing import List, Optional

from pydantic import BaseModel, Field

from app.controller.task_understanding.context import (
    FUSION_PATTERN,
    SAR_PATTERN,
    extract_context,
    extract_periods,
    extract_time_range,
)
from app.schemas.spatiotemporal import QueryContext

#: Phrases that request a comparison between dates. Multi-word phrases rather
#: than a bare "change": the singular form appears inside unrelated words, and
#: a request naming a *subject* of change ("vegetation change") would otherwise
#: fall through to that subject's index and silently compute the wrong thing on
#: a two-image upload.
CHANGE_PHRASES = (
    "change detection", "detect change", "changes", "changed", "before and after",
    "compare these two satellite images", "compare images", "change between",
    "change over", "change from", "vegetation change", "land cover change",
    "landcover change", "identify change", "find change", "measure change",
    "compare these two images", "compare the two images", "compare these images",
    "compare these two radar images", "compare the two radar images",
    # "What happened between these two images?" names no change word, but
    # asking about the span between two acquisitions is a comparison.
    "between these two images", "between the two images", "between these images",
    "between these two dates", "between the two dates", "between these dates",
)

#: "Has vegetation been lost between 2019 and 2025?" names no change word,
#: but something lost, gained, grown or shrunk across two named dates -- or
#: since one -- can only be measured by comparing two acquisitions.
CHANGE_VERB_PATTERN = re.compile(
    r"\b(lost|loss|gained|gain|gains|grown|grew|shrunk|shrank|shrinking|expanded|"
    r"expansion|increased?|decreased?|declined?|disappeared|deforest\w*|encroach\w*)\b"
)


def spans_two_dates(query: str) -> bool:
    """Whether a question names two dates, or a period open at its end ("since 2020")."""
    if len(extract_periods(query)) >= 2:
        return True
    period = extract_time_range(query)
    return period is not None and period.start is not None and period.end is None


#: A count asks for discrete objects -- unless what is being counted is a unit
#: of area or a pixel, which is a measurement, not a detection.
COUNT_PATTERN = re.compile(
    r"\b(how many|count|number of)\b(?!\s+(hectares?|acres?|km|square|sq|percent|"
    r"per cent|pixels?|metres?|meters?))"
)

FLOOD_PHRASES = ("flood", "inundat", "waterlogg", "water-logg", "submerged")

#: An explicit request for a description of the whole image.
CAPTION_PATTERN = re.compile(
    r"\bcaption\b|\bdescribe\s+(?:this|the)\s+(?:image|scene|picture|area)\b|"
    r"\bsummari[sz]e\s+(?:this|the)\s+(?:image|scene)\b|"
    r"\bdescription\s+of\s+(?:this|the)\s+(?:image|scene)\b"
)

#: Ordered: the first task whose phrases occur in the query wins, so the order
#: is the precedence. A comparison beats the subject being compared, a count
#: beats the thing counted, an explicit index name beats a topic word, and a
#: request to classify beats the classes it names.
TASK_PHRASES: list[tuple[str, tuple[str, ...]]] = [
    ("ndvi", ("ndvi",)),
    ("ndwi", ("ndwi",)),
    ("ndbi", ("ndbi",)),
    (
        "segmentation",
        ("segment", "segmentation", "land cover", "land-cover", "landcover",
         "land use", "land-use", "landuse", "lulc"),
    ),
    (
        "classification",
        ("classify", "classification", "land use classification",
         "scene classification"),
    ),
    ("ndvi", ("vegetation index", "vegetation health", "vegetation")),
    ("ndwi", ("water index", "water bodies", "waterbody", "surface water", "open water",
              "water extent", "water spread")),
    # Built-up index. Checked before object detection because these phrases
    # ask for the *extent* of built-up land, which is an index task, rather
    # than for discrete building objects.
    (
        "ndbi",
        ("built-up", "built up", "builtup", "built-up index", "impervious",
         "urban index", "urban expansion"),
    ),
    (
        "object_detection",
        ("detect buildings", "detect building", "buildings", "roads", "objects",
         "object detection", "lakes", "ponds", "reservoirs", "settlements",
         "clearings", "ships", "vehicles", "aircraft", "cars"),
    ),
    ("image_captioning", ("describe",)),
    (
        "image_analysis",
        ("what is in this image", "what does this image show",
         "analyze this image", "analyse this image"),
    ),
]


class TaskUnderstandingResult(BaseModel):
    """
    Structured interpretation of a user's remote-sensing query.
    """

    original_query: str
    task_type: Optional[str] = None
    objects: List[str] = Field(default_factory=list)
    requested_output: Optional[str] = None
    temporal_requirement: Optional[str] = None
    confidence: float = 0.0
    #: The modality of the supplied imagery, once the images are known:
    #: ``optical``, ``sar``, or ``optical+sar`` for a mixed pair. Filled in by
    #: :func:`adapt_to_imagery`; ``None`` from the sentence alone.
    imagery_modality: Optional[str] = None
    #: Location, time, metric and modality, as the sentence states them.
    context: QueryContext = Field(default_factory=QueryContext)


class TaskUnderstanding:
    """
    Deterministic first-stage task understanding.

    Converts a natural-language query into a structured representation.
    This component does not select tools/models or execute tasks.
    """

    def understand(self, query: str) -> TaskUnderstandingResult:
        if not isinstance(query, str):
            raise TypeError("query must be a string")

        query = query.strip()

        if not query:
            raise ValueError("query cannot be empty")

        query_lower = query.lower()

        task_type = self._detect_task_type(query_lower)
        objects = self._extract_objects(query_lower)
        requested_output = self._detect_output(query_lower)
        temporal_requirement = self._detect_temporal_requirement(query_lower)

        confidence = self._calculate_confidence(
            task_type=task_type,
            objects=objects,
            requested_output=requested_output,
        )

        return TaskUnderstandingResult(
            original_query=query,
            task_type=task_type,
            objects=objects,
            requested_output=requested_output,
            temporal_requirement=temporal_requirement,
            confidence=confidence,
            context=extract_context(query),
        )

    @staticmethod
    def _detect_task_type(query: str) -> Optional[str]:
        if any(phrase in query for phrase in CHANGE_PHRASES):
            return "change_detection"
        if CHANGE_VERB_PATTERN.search(query) and spans_two_dates(query):
            return "change_detection"
        if FUSION_PATTERN.search(query):
            return "optical_sar_fusion"
        if CAPTION_PATTERN.search(query):
            return "image_captioning"
        if COUNT_PATTERN.search(query):
            return "object_detection"
        if SAR_PATTERN.search(query):
            return "sar_analysis"
        if any(phrase in query for phrase in FLOOD_PHRASES):
            return "flood_mapping"
        for task, phrases in TASK_PHRASES:
            if any(phrase in query for phrase in phrases):
                return task
        return None

    @staticmethod
    def _extract_objects(query: str) -> List[str]:
        known_objects = [
            "buildings",
            "building",
            "roads",
            "water",
            "water bodies",
            "vegetation",
            "forest",
            "agriculture",
            "farmland",
            "urban areas",
            "urban area",
            "construction",
            "ships",
            "vehicles",
            "aircraft",
            "cars",
            "lakes",
            "ponds",
            "reservoirs",
            "rivers",
            "settlements",
            "clearings",
            "bare land",
            "bare soil",
        ]

        found = []

        for obj in known_objects:
            if obj in query and obj not in found:
                found.append(obj)

        return found

    @staticmethod
    def _detect_output(query: str) -> Optional[str]:
        if any(
            phrase in query
            for phrase in [
                "identify areas",
                "find areas",
                "locate areas",
                "show areas",
                "highlight areas",
            ]
        ):
            return "areas"

        if any(
                phrase in query
                for phrase in [
                    "calculate",
                    "compute",
                    "value of",
                    "index",
                ]
            ):
                return "index_value"

        if any(
                    phrase in query
                    for phrase in [
                        "detect",
                        "identify",
                        "find",
                        "locate",
                    ]
                ):
                    return "detections"

        if any(
                        phrase in query
                        for phrase in [
                            "classify",
                            "classification",
                        ]
                    ):
                        return "classification"

        if any(
                            phrase in query
                            for phrase in [
                                "segment",
                                "segmentation",
                            ]
                        ):
                            return "segmentation"

        return None

    @staticmethod
    def _detect_temporal_requirement(query: str) -> Optional[str]:
        if any(
            phrase in query
            for phrase in [
                "before and after",
                "over time",
                "between two dates",
                "different dates",
                "two time periods",
                "temporal change",
            ]
        ):
            return "multi_temporal"

        if any(
                phrase in query
                for phrase in [
                    "latest",
                    "recent",
                    "current",
                ]
            ):
                return "recent"

        return None

    @staticmethod
    def _calculate_confidence(
        task_type: Optional[str],
        objects: List[str],
        requested_output: Optional[str],
    ) -> float:
        score = 0.0

        if task_type is not None:
            score += 0.6

        if objects:
            score += 0.2

        if requested_output is not None:
            score += 0.2

        return min(score, 1.0)


def adapt_to_imagery(
    understanding: TaskUnderstandingResult,
    modalities: set[Optional[str]],
) -> tuple[TaskUnderstandingResult, Optional[str]]:
    """Fit a water-mapping request to the kind of imagery actually supplied.

    "Where is the water?" and "what flooded?" have different answers on
    different sensors: optical imagery measures water with NDWI, and radar
    imagery has no green or near-infrared band at all, so it maps water from
    backscatter instead. The sentence cannot tell the two apart; the uploaded
    files can, so this runs once the images are known.

    Only water mapping is adapted. Any other mismatch -- an NDVI request on a
    radar scene -- is left for the validator to reject with a clear reason,
    because there is no equivalent measurement to substitute.

    Returns the (possibly) adapted understanding and a note explaining the
    adaptation, or ``None`` when nothing changed. Either way the result records
    the shared modality of the imagery, which is what lets change detection
    compare two radar scenes by backscatter instead of by a spectral index.
    """
    if modalities == {"optical", "sar"}:
        shared = "optical+sar"
    else:
        shared = next(iter(modalities)) if len(modalities) == 1 else None
    understanding = understanding.model_copy(update={"imagery_modality": shared})

    task = understanding.task_type
    if shared == "optical+sar" and task in {"ndwi", "flood_mapping", "sar_analysis"}:
        # One image of each kind is exactly what fusion needs: radar maps
        # water through cloud, optical confirms it where the sky is clear.
        return understanding.model_copy(update={"task_type": "optical_sar_fusion"}), (
            "One optical and one SAR image were supplied, so water was mapped "
            "from both sensors and fused."
        )
    if task not in {"ndwi", "flood_mapping"}:
        return understanding, None

    if modalities and modalities <= {"sar"}:
        return understanding.model_copy(update={"task_type": "sar_analysis"}), (
            "The imagery is SAR, so water was mapped from radar backscatter "
            "rather than from NDWI, which needs optical bands."
        )
    if task == "flood_mapping":
        return understanding.model_copy(update={"task_type": "ndwi"}), (
            "The imagery is not SAR, so flooding was mapped as open surface "
            "water with NDWI."
        )
    return understanding, None
