import pytest

from app.controller.task_understanding import (
    TaskUnderstanding,
    TaskUnderstandingResult,
)


def test_change_detection_query():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Compare these two satellite images and identify areas where new construction has appeared."
    )

    assert isinstance(result, TaskUnderstandingResult)
    assert result.task_type == "change_detection"
    assert "construction" in result.objects
    assert result.requested_output == "areas"
    assert result.original_query.startswith("Compare")


def test_ndvi_query():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Calculate NDVI to analyze vegetation health."
    )

    assert result.task_type == "ndvi"
    assert "vegetation" in result.objects
    assert result.requested_output == "index_value"


def test_segmentation_query():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Segment the satellite image into different land cover classes."
    )

    assert result.task_type == "segmentation"
    assert result.requested_output == "segmentation"


def test_object_detection_query():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Detect buildings and roads in this satellite image."
    )

    assert result.task_type == "object_detection"
    assert "buildings" in result.objects
    assert "roads" in result.objects
    assert result.requested_output == "detections"


def test_temporal_requirement():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Compare satellite images from before and after construction."
    )

    assert result.task_type == "change_detection"
    assert result.temporal_requirement == "multi_temporal"


def test_unknown_query():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Tell me something about this satellite image."
    )

    assert result.task_type is None
    assert result.confidence == 0.0


def test_empty_query():
    understanding = TaskUnderstanding()

    with pytest.raises(ValueError):
        understanding.understand("")


def test_whitespace_query():
    understanding = TaskUnderstanding()

    with pytest.raises(ValueError):
        understanding.understand("   ")


def test_invalid_query_type():
    understanding = TaskUnderstanding()

    with pytest.raises(TypeError):
        understanding.understand(None)

def test_case_insensitive_query():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "CALCULATE NDVI TO ANALYZE VEGETATION."
    )

    assert result.task_type == "ndvi"
    assert "vegetation" in result.objects


def test_recent_query():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Analyze the latest satellite image for vegetation."
    )

    assert result.temporal_requirement == "recent"
    assert result.task_type == "ndvi"


def test_change_detection_with_dates():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Compare satellite images between two dates to detect changes."
    )

    assert result.task_type == "change_detection"
    assert result.temporal_requirement == "multi_temporal"


def test_building_detection():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Find buildings in this satellite image."
    )

    assert result.task_type == "object_detection"
    assert "buildings" in result.objects
    assert result.requested_output == "detections"


def test_result_preserves_original_query():
    understanding = TaskUnderstanding()

    query = "Calculate NDVI for this satellite image."

    result = understanding.understand(query)

    assert result.original_query == query


def test_confidence_for_clear_query():
    understanding = TaskUnderstanding()

    result = understanding.understand(
        "Detect buildings in this satellite image."
    )

    assert result.confidence > 0.0
    assert result.confidence <= 1.0

# ============================================================
# CHANGE VERSUS THE SUBJECT OF CHANGE
# ============================================================
@pytest.mark.parametrize(
    "query",
    [
        "Compare these two images and identify vegetation change",
        "Identify vegetation change between 2023 and 2025",
        "Show me land cover change",
        "Find change between these images",
        "Measure change over time",
        "Compare these images",
    ],
)
def test_a_request_naming_the_subject_of_change_is_still_change_detection(query):
    """"Vegetation change" is a comparison, not a vegetation index.

    Without this the phrase falls through to NDVI, and a two-image upload is
    then rejected for image count -- or worse, a single upload quietly returns
    a vegetation index in answer to a question about change.
    """
    assert TaskUnderstanding().understand(query).task_type == "change_detection"


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Calculate NDVI", "ndvi"),
        ("Show vegetation health", "ndvi"),
        ("vegetation index", "ndvi"),
        ("Show me the water bodies", "ndwi"),
        ("Find built-up area", "ndbi"),
    ],
)
def test_plain_index_requests_are_not_captured_by_the_change_phrases(query, expected):
    """The broader change matching must not swallow ordinary index requests."""
    assert TaskUnderstanding().understand(query).task_type == expected
