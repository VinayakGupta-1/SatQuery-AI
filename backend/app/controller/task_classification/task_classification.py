from typing import Optional

from pydantic import BaseModel

from app.controller.task_understanding import TaskUnderstandingResult


class TaskClassificationResult(BaseModel):
    """
    Classification of a remote-sensing task into a high-level
    SatQuery task category.
    """

    task_category: str
    source_task_type: Optional[str] = None
    confidence: float = 0.0


class TaskClassifier:
    """
    Classifies an already-understood task into a high-level
    remote-sensing task category.

    This component does not select tools or models.
    """

    def classify(
        self,
        understanding: TaskUnderstandingResult,
    ) -> TaskClassificationResult:

        if not isinstance(understanding, TaskUnderstandingResult):
            raise TypeError(
                "understanding must be a TaskUnderstandingResult"
            )

        task_type = understanding.task_type

        if task_type is None:
            return TaskClassificationResult(
                task_category="unknown",
                source_task_type=None,
                confidence=0.0,
            )

        classification_map = {
            "change_detection": "change_detection",
            "ndvi": "index_analysis",
            "ndwi": "index_analysis",
            "ndbi": "index_analysis",
            "object_detection": "object_detection",
            "segmentation": "segmentation",
            "classification": "scene_classification",
            "image_analysis": "image_analysis",
        }

        task_category = classification_map.get(
            task_type,
            "unknown",
        )

        confidence = self._calculate_confidence(
            understanding.confidence,
            task_category,
        )

        return TaskClassificationResult(
            task_category=task_category,
            source_task_type=task_type,
            confidence=confidence,
        )

    @staticmethod
    def _calculate_confidence(
        understanding_confidence: float,
        task_category: str,
    ) -> float:

        if task_category == "unknown":
            return 0.0

        return min(max(understanding_confidence, 0.0), 1.0)
