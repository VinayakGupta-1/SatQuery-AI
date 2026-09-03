"""Tests for stage 10 -- result integration and deterministic narration."""

from __future__ import annotations

import pytest

from app.controller.execution.orchestrator import ExecutionOrchestrator, ExecutionRequest
from app.controller.execution.orchestrator import ExecutionResult
from app.controller.planning.planner import PlanStep, TaskPlan
from app.controller.result_integration.integrator import ResultIntegrator
from app.controller.result_integration.narrators import (
    format_area,
    get_narrator,
    is_projected_crs,
)
from app.controller.tool_selection.selector import ToolSelectionResult
from app.schemas.errors import ErrorCode, ValidationIssue, ValidationResult
from app.schemas.results import FinalResult


@pytest.fixture
def integrator():
    return ResultIntegrator()


@pytest.fixture
def ndvi_execution(sentinel2_scene, tmp_path):
    """A real, completed NDVI execution to integrate."""
    return ExecutionOrchestrator().execute(
        ExecutionRequest(
            tool_id="ndvi",
            input_references=[sentinel2_scene],
            output_directory=str(tmp_path / "outputs"),
        )
    )


@pytest.fixture
def selection():
    return ToolSelectionResult(
        task_category="index_analysis",
        selected_tool_id="ndvi",
        selected_tool_name="NDVI",
        capability="index_analysis",
        selection_reason="Selected registered tool 'NDVI' because it satisfies the task.",
        confidence=0.9,
        status="selected",
    )


@pytest.fixture
def plan():
    return TaskPlan(
        task_category="index_analysis",
        steps=[
            PlanStep(step_id=1, action="validate", description="Validate the input imagery"),
            PlanStep(step_id=2, action="compute", description="Compute the spectral index"),
        ],
        required_capabilities=["index_analysis"],
    )


# ============================================================
# SUCCESSFUL INTEGRATION
# ============================================================
def test_completed_execution_becomes_a_final_result(
    integrator, ndvi_execution, selection, plan
):
    final = integrator.integrate(
        task_id="task_1",
        execution=ndvi_execution,
        query="Calculate NDVI",
        plan=plan,
        selection=selection,
        validation=ValidationResult(valid=True),
    )

    assert isinstance(final, FinalResult)
    assert final.task_id == "task_1"
    assert len(final.results) == 1
    assert final.results[0].result_type == "raster_index"
    assert final.execution_summary.tools_used == ["ndvi"]
    assert final.execution_summary.steps == [
        "Validate the input imagery",
        "Compute the spectral index",
    ]


def test_answer_reports_the_real_statistics(integrator, ndvi_execution):
    final = integrator.integrate(task_id="task_1", execution=ndvi_execution)

    # Mean NDVI for the fixture scene is exactly 0.2, range -0.5 to 0.8.
    assert "0.200" in final.answer
    assert "-0.500" in final.answer
    assert "0.800" in final.answer
    assert "All 4 pixels were computable" in final.answer
    assert "(B8 - B4) / (B8 + B4)" in final.answer


def test_answer_names_the_dominant_class_with_area(integrator, ndvi_execution):
    final = integrator.integrate(task_id="task_1", execution=ndvi_execution)

    # Four pixels land in four different classes, so the first maximum wins;
    # each covers one 10 m pixel, which is 100 m2.
    assert "predominantly" in final.answer
    assert "25.0%" in final.answer
    assert "100 m2" in final.answer


def test_result_data_carries_statistics_and_artifacts(integrator, ndvi_execution):
    final = integrator.integrate(task_id="task_1", execution=ndvi_execution)
    data = final.results[0].data

    assert data["index"] == "NDVI"
    assert data["statistics"]["mean"] == pytest.approx(0.2)
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0].endswith("_ndvi.tif")


def test_evidence_records_provenance(integrator, ndvi_execution, selection):
    final = integrator.integrate(
        task_id="task_1",
        execution=ndvi_execution,
        selection=selection,
        validation=ValidationResult(valid=True),
    )
    sources = {item.source for item in final.evidence}

    assert "formula" in sources
    assert "coverage" in sources
    assert "interpretation" in sources
    assert "tool_selection" in sources
    assert "input_validation" in sources


def test_coverage_evidence_carries_the_valid_fraction(integrator, ndvi_execution):
    final = integrator.integrate(task_id="task_1", execution=ndvi_execution)
    coverage = next(item for item in final.evidence if item.source == "coverage")

    assert coverage.confidence == pytest.approx(1.0)


def test_confidence_describes_tool_selection_not_pixel_accuracy(
    integrator, ndvi_execution, selection
):
    final = integrator.integrate(
        task_id="task_1", execution=ndvi_execution, selection=selection
    )

    assert final.confidence == pytest.approx(0.9)
    # The deterministic index itself reports no probabilistic confidence.
    assert final.results[0].confidence is None


# ============================================================
# PARTIAL AND EMPTY RESULTS
# ============================================================
def test_partial_coverage_is_stated_honestly(integrator, raster_factory, tmp_path):
    from tests.conftest import make_band

    red = make_band("B4", [1000, 9999], 2, 1, nodata=9999)
    nir = make_band("B8", [3000, 3000], 2, 1, nodata=9999)
    path = raster_factory("masked.tif", [red, nir], nodata=9999)

    execution = ExecutionOrchestrator().execute(
        ExecutionRequest(
            tool_id="ndvi",
            input_references=[path],
            output_directory=str(tmp_path / "outputs"),
        )
    )
    final = integrator.integrate(task_id="task_1", execution=execution)

    assert "1 of 2 pixels were computable (50.0%)" in final.answer
    assert "nodata" in final.answer


def test_a_scene_with_nothing_computable_says_so(integrator, raster_factory, tmp_path):
    from tests.conftest import make_band

    red = make_band("B4", [0, 0], 2, 1)
    nir = make_band("B8", [0, 0], 2, 1)
    path = raster_factory("allzero.tif", [red, nir])

    execution = ExecutionOrchestrator().execute(
        ExecutionRequest(
            tool_id="ndvi",
            input_references=[path],
            output_directory=str(tmp_path / "outputs"),
        )
    )
    final = integrator.integrate(task_id="task_1", execution=execution)

    assert "could not be computed anywhere" in final.answer
    # No mean is claimed, because there is none.
    assert "Mean" not in final.answer


# ============================================================
# UNSUCCESSFUL OUTCOMES USE THE SAME CONTRACT
# ============================================================
def test_validation_failure_becomes_a_final_result(integrator, plan):
    validation = ValidationResult(
        valid=False,
        errors=[
            ValidationIssue(
                code=ErrorCode.MODALITY_MISMATCH,
                message="Image 'scene_1' must be optical.",
                field="images.scene_1.metadata.modality",
            )
        ],
    )

    final = integrator.integrate(
        task_id="task_1", validation=validation, plan=plan
    )

    assert isinstance(final, FinalResult)
    assert "rejected before execution by 1 validation check" in final.answer
    assert "must be optical" in final.answer
    assert final.results == []
    assert final.evidence[0].source == "MODALITY_MISMATCH"


def test_blocked_execution_becomes_a_final_result(integrator, sentinel2_scene):
    execution = ExecutionOrchestrator().execute(
        ExecutionRequest(tool_id="satellite_vqa", input_references=[sentinel2_scene])
    )

    final = integrator.integrate(task_id="task_1", execution=execution)

    assert "blocked before the tool ran" in final.answer
    assert "no execution implementation" in final.answer
    assert final.results == []


def test_failed_execution_becomes_a_final_result(integrator, tmp_path):
    execution = ExecutionOrchestrator().execute(
        ExecutionRequest(
            tool_id="ndvi", input_references=[str(tmp_path / "absent.tif")]
        )
    )

    final = integrator.integrate(task_id="task_1", execution=execution)

    assert "did not complete" in final.answer
    assert "not found" in final.answer
    assert final.results == []


def test_no_execution_reports_the_selection_reason(integrator):
    selection = ToolSelectionResult(
        task_category="unknown",
        selection_reason="Task category is unknown.",
        status="requires_clarification",
    )

    final = integrator.integrate(task_id="task_1", selection=selection)

    assert "did not reach execution" in final.answer
    assert "Task category is unknown." in final.answer
    assert final.execution_summary.tools_used == []


def test_a_selected_but_unrun_tool_is_still_named(integrator, selection, sentinel2_scene):
    execution = ExecutionOrchestrator().execute(
        ExecutionRequest(tool_id="ndvi", input_references=[str("absent.tif")])
    )

    final = integrator.integrate(
        task_id="task_1", execution=execution, selection=selection
    )

    assert final.execution_summary.tools_used == ["ndvi"]
    assert final.results == []


# ============================================================
# INPUT GUARDS
# ============================================================
def test_task_id_is_required(integrator):
    with pytest.raises(ValueError):
        integrator.integrate(task_id="   ")


def test_execution_must_be_an_execution_result(integrator):
    with pytest.raises(TypeError):
        integrator.integrate(task_id="task_1", execution={"status": "completed"})


def test_unknown_result_type_falls_back_to_the_generic_narrator(integrator):
    execution = ExecutionResult(
        tool_id="future_tool",
        status="completed",
        output={
            "tool_id": "future_tool",
            "result_type": "bounding_boxes",
            "data": {},
            "statistics": {"valid_pixels": 3, "total_pixels": 4},
            "artifacts": [],
            "metadata": {},
        },
    )

    final = integrator.integrate(task_id="task_1", execution=execution)

    assert "bounding boxes" in final.answer
    assert "3 of 4 pixels" in final.answer
    assert final.results[0].result_type == "bounding_boxes"


# ============================================================
# UNIT HANDLING
# ============================================================
def test_projected_and_geographic_crs_are_distinguished():
    assert is_projected_crs("EPSG:32643")  # UTM 43N, metres
    assert not is_projected_crs("EPSG:4326")  # WGS84, degrees
    assert not is_projected_crs(None)
    assert not is_projected_crs("local")


def test_area_is_never_converted_for_a_geographic_crs(
    integrator, raster_factory, tmp_path
):
    from app.tools.raster.model import GeoReference
    from tests.conftest import make_band

    # In EPSG:4326 a "pixel area" is in square degrees, whose ground size
    # varies with latitude. Reporting it as hectares would be plainly wrong.
    red = make_band("B4", [1000, 2000], 2, 1)
    nir = make_band("B8", [3000, 2000], 2, 1)
    path = raster_factory(
        "wgs84.tif",
        [red, nir],
        georeference=GeoReference(
            crs="EPSG:4326", transform=(77.0, 0.0001, 0.0, 28.0, 0.0, -0.0001)
        ),
    )

    execution = ExecutionOrchestrator().execute(
        ExecutionRequest(
            tool_id="ndvi",
            input_references=[path],
            output_directory=str(tmp_path / "outputs"),
        )
    )
    final = integrator.integrate(task_id="task_1", execution=execution)

    assert "predominantly" in final.answer
    assert "ha" not in final.answer
    assert "km2" not in final.answer
    assert "m2" not in final.answer


def test_area_formatting_picks_a_readable_unit():
    assert format_area(500) == "500 m2"
    assert format_area(50_000) == "5.00 ha"
    assert format_area(5_000_000) == "5.00 km2"


def test_narrator_lookup_falls_back():
    assert get_narrator("raster_index").result_type == "raster_index"
    assert get_narrator("does_not_exist").result_type == "generic"
    assert get_narrator(None).result_type == "generic"
