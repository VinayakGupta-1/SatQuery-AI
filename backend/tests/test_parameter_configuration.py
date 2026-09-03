import pytest

from app.controller.parameter_configuration.configurator import (
    ParameterConfiguration,
    ParameterConfigurator,
)

from app.controller.task_understanding.task_understanding import (
    TaskUnderstandingResult,
)

from app.controller.task_classification.task_classification import (
    TaskClassificationResult,
)

from app.controller.planning.planner import TaskPlan

from app.controller.input_requirements.input_requirements import (
    InputRequirements,
)

from app.controller.tool_selection.selector import (
    ToolSelectionResult,
)


@pytest.fixture
def configurator():
    return ParameterConfigurator()


def build_inputs(
    task_type,
    category,
    tool_id,
    requirements,
):
    understanding = TaskUnderstandingResult(
        original_query="test query",
        task_type=task_type,
        objects=["buildings"] if task_type == "object_detection" else [],
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

    selection = ToolSelectionResult(
        task_category=category,
        selected_tool_id=tool_id,
        selected_tool_name=tool_id,
        capability=category,
        confidence=0.9,
        status="selected",
    )

    return (
understanding,
classification,
plan,
requirements,
selection,
)


def test_ndvi_parameters_are_resolved(configurator):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["red", "nir"],
    )

    inputs = build_inputs(
        "ndvi",
        "index_analysis",
        "ndvi",
        requirements,
    )

    result = configurator.configure(*inputs)

    assert isinstance(result, ParameterConfiguration)
    assert result.status == "configured"
    assert result.resolved_parameters["red_band"] == "red"
    assert result.resolved_parameters["nir_band"] == "nir"


def test_ndwi_parameters_are_resolved(configurator):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["green", "nir"],
    )

    inputs = build_inputs(
        "ndwi",
        "index_analysis",
        "ndwi",
        requirements,
    )

    result = configurator.configure(*inputs)

    assert result.status == "configured"
    assert result.resolved_parameters["green_band"] == "green"
    assert result.resolved_parameters["nir_band"] == "nir"


def test_ndbi_parameters_are_resolved(configurator):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["nir", "swir"],
    )

    inputs = build_inputs(
        "ndbi",
        "index_analysis",
        "ndbi",
        requirements,
    )

    result = configurator.configure(*inputs)

    assert result.status == "configured"
    assert result.resolved_parameters["nir_band"] == "nir"
    assert result.resolved_parameters["swir_band"] == "swir"


def test_object_detection_uses_understood_objects(configurator):
    requirements = InputRequirements(
        task_category="object_detection",
        minimum_image_count=1,
        required_modalities=["compatible_imagery"],
    )

    inputs = build_inputs(
        "object_detection",
        "object_detection",
        "object_detection",
        requirements,
    )

    result = configurator.configure(*inputs)

    assert result.status == "configured"
    assert result.resolved_parameters["target_objects"] == [
        "buildings"
    ]


def test_explicit_parameters_have_priority(configurator):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["red", "nir"],
    )

    inputs = build_inputs(
        "ndvi",
        "index_analysis",
        "ndvi",
        requirements,
    )

    result = configurator.configure(
        *inputs,
        user_parameters={
            "red_band": "B4",
            "nir_band": "B8",
        },
    )

    assert result.status == "configured"
    assert result.resolved_parameters["red_band"] == "B4"
    assert result.resolved_parameters["nir_band"] == "B8"


def test_unknown_parameter_is_rejected(configurator):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
    )

    inputs = build_inputs(
        "ndvi",
        "index_analysis",
        "ndvi",
        requirements,
    )

    # Current NDVI Registry has no configurable parameters.
    result = configurator.configure(
        *inputs,
        user_parameters={
            "unknown_parameter": 10,
        },
    )

    assert result.status == "invalid"
    assert len(result.validation_errors) > 0


def test_unselected_tool_is_rejected(configurator):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
    )

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

    plan = TaskPlan(
        task_category="index_analysis",
        steps=[],
        required_capabilities=[],
    )

    selection = ToolSelectionResult(
        task_category="index_analysis",
        capability="index_analysis",
        status="no_compatible_tool",
    )

    result = configurator.configure(
        understanding,
        classification,
        plan,
        requirements,
        selection,
    )

    assert result.status == "needs_input"


def test_nonexistent_tool_is_rejected(configurator):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
    )

    inputs = build_inputs(
        "ndvi",
        "index_analysis",
        "does_not_exist",
        requirements,
    )

    result = configurator.configure(*inputs)

    assert result.status == "invalid"


def test_confidence_is_bounded(configurator):
    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
        required_bands=["red", "nir"],
    )

    inputs = build_inputs(
        "ndvi",
        "index_analysis",
        "ndvi",
        requirements,
    )

    result = configurator.configure(*inputs)

    assert 0.0 <= result.confidence <= 1.0


def test_invalid_understanding(configurator):
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

    selection = ToolSelectionResult(
        task_category="index_analysis",
        selected_tool_id="ndvi",
        status="selected",
    )

    with pytest.raises(TypeError):
        configurator.configure(
            "invalid",
            classification,
            plan,
            requirements,
            selection,
        )


def test_invalid_classification(configurator):
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

    selection = ToolSelectionResult(
        task_category="index_analysis",
        selected_tool_id="ndvi",
        status="selected",
    )

    with pytest.raises(TypeError):
        configurator.configure(
            understanding,
            "invalid",
            plan,
            requirements,
            selection,
        )


def test_invalid_plan(configurator):
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

    selection = ToolSelectionResult(
        task_category="index_analysis",
        selected_tool_id="ndvi",
        status="selected",
    )

    with pytest.raises(TypeError):
        configurator.configure(
            understanding,
            classification,
            "invalid",
            requirements,
            selection,
        )


def test_invalid_requirements(configurator):
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

    selection = ToolSelectionResult(
        task_category="index_analysis",
        selected_tool_id="ndvi",
        status="selected",
    )

    with pytest.raises(TypeError):
        configurator.configure(
            understanding,
            classification,
            plan,
            "invalid",
            selection,
        )


def test_invalid_selection(configurator):
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

    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
    )

    with pytest.raises(TypeError):
        configurator.configure(
            understanding,
            classification,
            plan,
            requirements,
            "invalid",
        )