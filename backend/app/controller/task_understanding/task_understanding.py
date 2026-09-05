from typing import List, Optional
from pydantic import BaseModel, Field


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
        )

    @staticmethod
    def _detect_task_type(query: str) -> Optional[str]:
        if any(
            keyword in query
            for keyword in [
                "change detection",
                "detect change",
                "changes",
                "changed",
                "before and after",
                "compare these two satellite images",
                "compare images",
                # Multi-word phrases rather than a bare "change": the singular
                # form appears inside unrelated words, and a request naming a
                # *subject* of change ("vegetation change") would otherwise
                # fall through to that subject's index and silently compute
                # the wrong thing on a two-image upload.
                "change between",
                "change over",
                "change from",
                "vegetation change",
                "land cover change",
                "landcover change",
                "identify change",
                "find change",
                "measure change",
                "compare these two images",
                "compare the two images",
                "compare these images",
            ]
        ):
            return "change_detection"

        if any(
                keyword in query
                for keyword in [
                    "ndvi",
                    "vegetation index",
                    "vegetation health",
                    "vegetation",
                ]
            ):
                return "ndvi"

        if any(
                    keyword in query
                    for keyword in [
                        "ndwi",
                        "water index",
                        "water bodies",
                        "waterbody",
                        "water bodies",
                    ]
                ):
                    return "ndwi"

        # Built-up index. Checked before object detection because these
        # phrases ask for the *extent* of built-up land, which is an index
        # task, rather than for discrete building objects.
        if any(
            keyword in query
            for keyword in [
                "ndbi",
                "built-up",
                "built up",
                "builtup",
                "built-up index",
                "impervious",
                "urban index",
                "urban expansion",
            ]
        ):
            return "ndbi"

        if any(
                        keyword in query
                        for keyword in [
                            "detect buildings",
                            "detect building",
                            "buildings",
                            "roads",
                            "objects",
                            "object detection",
                        ]
                    ):
                        return "object_detection"

        if any(
                            keyword in query
                            for keyword in [
                                "segment",
                                "segmentation",
                                "land cover",
                                "land-cover",
                            ]
                        ):
                            return "segmentation"

        if any(
                                keyword in query
                                for keyword in [
                                    "classify",
                                    "classification",
                                    "land use classification",
                                    "scene classification",
                                ]
                            ):
                                return "classification"

        if any(
                                    keyword in query
                                    for keyword in [
                                        "describe",
                                        "what is in this image",
                                        "what does this image show",
                                        "analyze this image",
                                    ]
                                ):
                                    return "image_analysis"

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
