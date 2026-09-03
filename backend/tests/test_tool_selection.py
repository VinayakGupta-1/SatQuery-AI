import pytest

from app.controller.tool_selection.selector import (
    ToolCandidate,
    ToolSelectionResult,
    ToolSelector,
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

from app.controller.input_requirements.input_requirements import (
    InputRequirements,
)


@pytest.fixture
def selector():
    return ToolSelector()


def make_inputs(task_type, category, requirements):
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

    return understanding, classification, plan, requirements


def test_ndvi_selects_ndvi_tool(selector):
    requirements = InputRequirements(
        task_category="index_analysis",
        required_inputs=["satellite_image"],
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["red", "nir"],
        requires_metadata=True,
        requires_crs=True,
    )

    inputs = make_inputs("ndvi", "index_analysis", requirements)

    result = selector.select(*inputs)

    assert isinstance(result, ToolSelectionResult)
    assert result.status == "selected"
    assert result.selected_tool_id == "ndvi"


def test_ndwi_selects_ndwi_tool(selector):
    requirements = InputRequirements(
        task_category="index_analysis",
        required_inputs=["satellite_image"],
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["green", "nir"],
    )

    inputs = make_inputs("ndwi", "index_analysis", requirements)

    result = selector.select(*inputs)

    assert result.selected_tool_id == "ndwi"


def test_change_detection_selects_correct_tool(selector):
    requirements = InputRequirements(
        task_category="change_detection",
        required_inputs=["image_1", "image_2"],
        minimum_image_count=2,
        required_modalities=["compatible_modality"],
        requires_temporal_information=True,
        requires_crs=True,
    )

    inputs = make_inputs(
        "change_detection",
        "change_detection",
        requirements,
    )

    result = selector.select(*inputs)

    assert result.selected_tool_id == "change_detection"


def test_object_detection_selects_correct_tool(selector):
    requirements = InputRequirements(
        task_category="object_detection",
        required_inputs=["satellite_image"],
        minimum_image_count=1,
        required_modalities=["compatible_imagery"],
    )

    inputs = make_inputs(
        "object_detection",
        "object_detection",
        requirements,
    )

    result = selector.select(*inputs)

    assert result.selected_tool_id == "object_detection"


def test_classification_selects_land_cover_tool(selector):
    requirements = InputRequirements(
        task_category="scene_classification",
        required_inputs=["satellite_image"],
        minimum_image_count=1,
        required_modalities=["compatible_imagery"],
    )

    inputs = make_inputs(
        "classification",
        "scene_classification",
        requirements,
    )

    result = selector.select(*inputs)

    assert result.selected_tool_id == "land_cover_classification"


def test_no_tool_for_unknown_task(selector):
    requirements = InputRequirements(
        task_category="unknown",
    )

    inputs = make_inputs(
        None,
        "unknown",
        requirements,
    )

    result = selector.select(*inputs)

    assert result.status == "requires_clarification"
    assert result.selected_tool_id is None


def test_no_tool_when_image_count_incompatible(selector):
    requirements = InputRequirements(
        task_category="object_detection",
        required_inputs=["satellite_image"],
        minimum_image_count=2,
        required_modalities=["optical"],
    )

    inputs = make_inputs(
        "object_detection",
        "object_detection",
        requirements,
    )

    result = selector.select(*inputs)

    assert result.status == "no_compatible_tool"
    assert result.selected_tool_id is None


def test_no_tool_when_bands_incompatible(selector):
    requirements = InputRequirements(
        task_category="index_analysis",
        required_inputs=["satellite_image"],
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["swir", "blue"],
    )

    inputs = make_inputs(
        "ndvi",
        "index_analysis",
        requirements,
    )

    result = selector.select(*inputs)

    assert result.status == "no_compatible_tool"


def test_confidence_is_bounded(selector):
    requirements = InputRequirements(
        task_category="index_analysis",
        required_inputs=["satellite_image"],
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["red", "nir"],
    )

    inputs = make_inputs("ndvi", "index_analysis", requirements)

    result = selector.select(*inputs)

    assert 0.0 <= result.confidence <= 1.0


def test_alternatives_are_tool_candidates(selector):
    requirements = InputRequirements(
        task_category="index_analysis",
        required_inputs=["satellite_image"],
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["red", "nir"],
    )

    inputs = make_inputs("ndvi", "index_analysis", requirements)

    result = selector.select(*inputs)

    assert isinstance(result, ToolSelectionResult)

    for candidate in result.alternatives:
        assert isinstance(candidate, ToolCandidate)


def test_invalid_understanding(selector):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
    )

    classification = TaskClassificationResult(
        task_category="index_analysis",
        confidence=0.9,
    )

    plan = TaskPlan(
        task_category="index_analysis",
        steps=[],
        required_capabilities=[],
    )

    with pytest.raises(TypeError):
        selector.select(
            "invalid",
            classification,
            plan,
            requirements,
        )


def test_invalid_classification(selector):
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

    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
    )

    with pytest.raises(TypeError):
        selector.select(
            understanding,
            "invalid",
            plan,
            requirements,
        )


def test_invalid_plan(selector):
    understanding = TaskUnderstandingResult(
        original_query="calculate NDVI",
        task_type="ndvi",
        confidence=0.9,
    )

    classification = TaskClassificationResult(
        task_category="index_analysis",
        confidence=0.9,
    )

    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
    )

    with pytest.raises(TypeError):
        selector.select(
            understanding,
            classification,
            "invalid",
            requirements,
        )


def test_invalid_requirements(selector):
    understanding = TaskUnderstandingResult(
        original_query="calculate NDVI",
        task_type="ndvi",
        confidence=0.9,
    )

    classification = TaskClassificationResult(
        task_category="index_analysis",
        confidence=0.9,
    )

    plan = TaskPlan(
        task_category="index_analysis",
        steps=[],
        required_capabilities=[],
    )

    with pytest.raises(TypeError):
        selector.select(
            understanding,
            classification,
            plan,
            "invalid",
        )