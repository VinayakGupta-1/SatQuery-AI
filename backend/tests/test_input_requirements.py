import pytest

from app.controller.input_requirements.input_requirements import (
    InputRequirements,
    InputRequirementsResolver,
)

from app.controller.task_understanding.task_understanding import (
    TaskUnderstandingResult,
)

from app.controller.task_classification.task_classification import (
    TaskClassificationResult,
)

from app.controller.planning.planner import (
    TaskPlan,
)


@pytest.fixture
def resolver():
    return InputRequirementsResolver()


def make_inputs(task_type, category):
    understanding = TaskUnderstandingResult(
        original_query="test query",
        task_type=task_type,
        confidence=0.9,
    )

    classification = TaskClassificationResult(
        task_category=category,
        source_task_type=task_type,
        confidence=0.9,
    )

    plan = TaskPlan(
        task_category=category,
        steps=[],
        required_capabilities=[],
    )

    return understanding, classification, plan


def test_change_detection_requirements(resolver):
    understanding, classification, plan = make_inputs(
        "change_detection",
        "change_detection",
    )

    result = resolver.resolve(
        understanding,
        classification,
        plan,
    )

    assert isinstance(result, InputRequirements)
    assert result.minimum_image_count == 2
    assert "image_1" in result.required_inputs
    assert "image_2" in result.required_inputs
    assert result.requires_temporal_information is True
    assert result.requires_crs is True


def test_ndvi_requirements(resolver):
    understanding, classification, plan = make_inputs(
        "ndvi",
        "index_analysis",
    )

    result = resolver.resolve(
        understanding,
        classification,
        plan,
    )

    assert result.minimum_image_count == 1
    assert result.required_bands == ["red", "nir"]
    assert "optical" in result.required_modalities


def test_ndwi_requirements(resolver):
    understanding, classification, plan = make_inputs(
        "ndwi",
        "index_analysis",
    )

    result = resolver.resolve(
        understanding,
        classification,
        plan,
    )

    assert result.required_bands == ["green", "nir"]


def test_object_detection_requirements(resolver):
    understanding, classification, plan = make_inputs(
        "object_detection",
        "object_detection",
    )

    result = resolver.resolve(
        understanding,
        classification,
        plan,
    )

    assert result.minimum_image_count == 1
    assert "satellite_image" in result.required_inputs
    assert result.requires_metadata is True


def test_segmentation_requirements(resolver):
    understanding, classification, plan = make_inputs(
        "segmentation",
        "segmentation",
    )

    result = resolver.resolve(
        understanding,
        classification,
        plan,
    )

    assert result.minimum_image_count == 1
    assert result.requires_crs is True


def test_scene_classification_requirements(resolver):
    understanding, classification, plan = make_inputs(
        "classification",
        "scene_classification",
    )

    result = resolver.resolve(
        understanding,
        classification,
        plan,
    )

    assert result.minimum_image_count == 1


def test_image_analysis_requirements(resolver):
    understanding, classification, plan = make_inputs(
        "image_analysis",
        "image_analysis",
    )

    result = resolver.resolve(
        understanding,
        classification,
        plan,
    )

    assert result.minimum_image_count == 1
    assert result.requires_metadata is True


def test_unknown_requirements(resolver):
    understanding, classification, plan = make_inputs(
        None,
        "unknown",
    )

    result = resolver.resolve(
        understanding,
        classification,
        plan,
    )

    assert result.task_category == "unknown"
    assert result.required_inputs == []
    assert result.minimum_image_count == 0


def test_invalid_understanding(resolver):
    classification = TaskClassificationResult(
        task_category="ndvi",
        confidence=0.9,
    )

    plan = TaskPlan(
        task_category="ndvi",
        steps=[],
        required_capabilities=[],
    )

    with pytest.raises(TypeError):
        resolver.resolve(
            "invalid",
            classification,
            plan,
        )


def test_invalid_classification(resolver):
    understanding = TaskUnderstandingResult(
        original_query="calculate NDVI",
        task_type="ndvi",
        confidence=0.9,
    )

    plan = TaskPlan(
        task_category="index_analysis",
        steps=[],
        required_capabilities=[],
    )

    with pytest.raises(TypeError):
        resolver.resolve(
            understanding,
            "invalid",
            plan,
        )


def test_invalid_plan(resolver):
    understanding = TaskUnderstandingResult(
        original_query="calculate NDVI",
        task_type="ndvi",
        confidence=0.9,
    )

    classification = TaskClassificationResult(
        task_category="index_analysis",
        source_task_type="ndvi",
        confidence=0.9,
    )

    with pytest.raises(TypeError):
        resolver.resolve(
            understanding,
            classification,
            "invalid",
        )