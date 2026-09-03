import pytest

from app.controller.task_classification import (
    TaskClassifier,
    TaskClassificationResult,
)
from app.controller.task_understanding import TaskUnderstanding


def test_change_detection_classification():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Compare these two satellite images and identify areas "
        "where new construction has appeared."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert isinstance(result, TaskClassificationResult)
    assert result.task_category == "change_detection"
    assert result.source_task_type == "change_detection"
    assert result.confidence > 0.0


def test_ndvi_classification():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Calculate NDVI to analyze vegetation health."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert result.task_category == "index_analysis"
    assert result.source_task_type == "ndvi"


def test_ndwi_classification():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Calculate NDWI to identify water bodies."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert result.task_category == "index_analysis"
    assert result.source_task_type == "ndwi"


def test_object_detection_classification():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Detect buildings and roads in this satellite image."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert result.task_category == "object_detection"
    assert result.source_task_type == "object_detection"


def test_segmentation_classification():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Segment this satellite image into land cover classes."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert result.task_category == "segmentation"
    assert result.source_task_type == "segmentation"


def test_scene_classification():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Classify the scene in this satellite image."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert result.task_category == "scene_classification"
    assert result.source_task_type == "classification"


def test_image_analysis_classification():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Describe what is present in this satellite image."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert result.task_category == "image_analysis"
    assert result.source_task_type == "image_analysis"


def test_unknown_task_classification():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Tell me something about this satellite image."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert result.task_category == "unknown"
    assert result.source_task_type is None
    assert result.confidence == 0.0


def test_invalid_input():
    classifier = TaskClassifier()

    with pytest.raises(TypeError):
        classifier.classify(None)


def test_confidence_is_bounded():
    understanding = TaskUnderstanding()

    task = understanding.understand(
        "Detect buildings in this satellite image."
    )

    classifier = TaskClassifier()

    result = classifier.classify(task)

    assert 0.0 <= result.confidence <= 1.0