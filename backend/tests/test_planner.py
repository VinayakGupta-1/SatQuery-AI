import pytest

from app.controller.planning import Planner, PlanStep, TaskPlan
from app.controller.task_understanding import TaskUnderstanding
from app.controller.task_classification import TaskClassifier


def build_task(query):
    understanding = TaskUnderstanding().understand(query)
    classification = TaskClassifier().classify(understanding)
    return understanding, classification


def test_change_detection_plan():
    understanding, classification = build_task(
        "Compare these two satellite images and identify areas "
        "where new construction has appeared."
    )

    plan = Planner().create_plan(
        understanding,
        classification,
    )

    assert isinstance(plan, TaskPlan)
    assert plan.task_category == "change_detection"
    assert len(plan.steps) == 6
    assert plan.steps[0].action == "validate_inputs"
    assert plan.steps[4].action == "run_change_detection"
    assert "change_detection" in plan.required_capabilities
    assert plan.status == "planned"


def test_ndvi_plan():
    understanding, classification = build_task(
        "Calculate NDVI to analyze vegetation health."
    )

    plan = Planner().create_plan(
        understanding,
        classification,
    )

    assert plan.task_category == "index_analysis"
    assert len(plan.steps) == 5
    assert plan.steps[1].action == "check_required_bands"
    assert plan.steps[3].action == "calculate_index"
    assert "index_computation" in plan.required_capabilities


def test_object_detection_plan():
    understanding, classification = build_task(
        "Detect buildings in this satellite image."
    )

    plan = Planner().create_plan(
        understanding,
        classification,
    )

    assert plan.task_category == "object_detection"
    assert len(plan.steps) == 5
    assert plan.steps[3].action == "run_object_detection"
    assert "object_detection" in plan.required_capabilities


def test_segmentation_plan():
    understanding, classification = build_task(
        "Segment this satellite image into land cover classes."
    )

    plan = Planner().create_plan(
        understanding,
        classification,
    )

    assert plan.task_category == "segmentation"
    assert len(plan.steps) == 5
    assert plan.steps[3].action == "run_segmentation"
    assert "segmentation" in plan.required_capabilities


def test_scene_classification_plan():
    understanding, classification = build_task(
        "Classify the scene in this satellite image."
    )

    plan = Planner().create_plan(
        understanding,
        classification,
    )

    assert plan.task_category == "scene_classification"
    assert len(plan.steps) == 5
    assert plan.steps[3].action == "run_classification"


def test_image_analysis_plan():
    understanding, classification = build_task(
        "Describe what is present in this satellite image."
    )

    plan = Planner().create_plan(
        understanding,
        classification,
    )

    assert plan.task_category == "image_analysis"
    assert len(plan.steps) == 4
    assert plan.steps[2].action == "analyze_image"


def test_unknown_plan():
    understanding, classification = build_task(
        "Tell me something about this satellite image."
    )

    plan = Planner().create_plan(
        understanding,
        classification,
    )

    assert plan.task_category == "unknown"
    assert plan.steps == []
    assert plan.required_capabilities == []
    assert plan.status == "requires_clarification"


def test_invalid_understanding():
    classifier = TaskClassifier()

    classification = classifier.classify(
        TaskUnderstanding().understand(
            "Detect buildings in this satellite image."
        )
    )

    with pytest.raises(TypeError):
        Planner().create_plan(
            None,
            classification,
        )


def test_invalid_classification():
    understanding = TaskUnderstanding().understand(
        "Detect buildings in this satellite image."
    )

    with pytest.raises(TypeError):
        Planner().create_plan(
            understanding,
            None,
        )


def test_plan_steps_have_valid_ids():
    understanding, classification = build_task(
        "Detect buildings in this satellite image."
    )

    plan = Planner().create_plan(
        understanding,
        classification,
    )

    assert all(
        isinstance(step, PlanStep)
        for step in plan.steps
    )

    assert [
        step.step_id for step in plan.steps
    ] == list(range(1, len(plan.steps) + 1))