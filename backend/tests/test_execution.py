import pytest

from app.controller.execution.orchestrator import (
    ExecutionOrchestrator,
    ExecutionRequest,
    ExecutionResult,
)


@pytest.fixture
def orchestrator():
    return ExecutionOrchestrator()


def test_valid_execution(orchestrator, sentinel2_scene, tmp_path):
    request = ExecutionRequest(
        tool_id="ndvi",
        parameters={},
        input_references=[sentinel2_scene],
        output_directory=str(tmp_path / "outputs"),
    )

    result = orchestrator.execute(request)

    assert isinstance(result, ExecutionResult)
    assert result.status == "completed"
    assert result.tool_id == "ndvi"
    assert result.output is not None


def test_nonexistent_tool(orchestrator):
    request = ExecutionRequest(
        tool_id="does_not_exist",
        input_references=["image_001.tif"],
    )

    result = orchestrator.execute(request)

    assert result.status == "failed"
    assert result.error is not None


def test_disabled_tool(orchestrator, monkeypatch):
    from app.registry.registry import TOOLS

    tool = next(tool for tool in TOOLS if tool.tool_id == "ndvi")

    original = tool.enabled
    tool.enabled = False

    try:
        request = ExecutionRequest(
            tool_id="ndvi",
            input_references=["image_001.tif"],
        )

        result = orchestrator.execute(request)

        assert result.status == "blocked"
        assert result.error is not None

    finally:
        tool.enabled = original


def test_missing_input_reference(orchestrator):
    request = ExecutionRequest(
        tool_id="ndvi",
        parameters={},
        input_references=[],
    )

    result = orchestrator.execute(request)

    assert result.status == "blocked"
    assert result.error is not None


def test_missing_required_parameter(orchestrator, monkeypatch):
    from app.registry.registry import TOOLS

    tool = next(tool for tool in TOOLS if tool.tool_id == "ndvi")

    original_parameters = tool.parameters

    tool.parameters = {
        "red_band": "required:str",
        "nir_band": "required:str",
    }

    try:
        request = ExecutionRequest(
            tool_id="ndvi",
            parameters={
                "red_band": "B4",
            },
            input_references=["image_001.tif"],
        )

        result = orchestrator.execute(request)

        assert result.status == "blocked"
        assert "nir_band" in result.error

    finally:
        tool.parameters = original_parameters


def test_unknown_parameter(orchestrator):
    request = ExecutionRequest(
        tool_id="ndvi",
        parameters={
            "unknown_parameter": "value",
        },
        input_references=["image_001.tif"],
    )

    result = orchestrator.execute(request)

    assert result.status == "failed"
    assert result.error is not None


def test_execution_metadata(orchestrator, sentinel2_scene, tmp_path):
    request = ExecutionRequest(
        tool_id="ndvi",
        input_references=[sentinel2_scene],
        output_directory=str(tmp_path / "outputs"),
    )

    result = orchestrator.execute(request)

    assert result.status == "completed"
    assert result.execution_metadata["tool_name"] == "NDVI"
    assert result.execution_metadata["tool_type"] == "index"
    assert result.execution_metadata["input_count"] == 1
    assert result.execution_metadata["result_type"] == "raster_index"


def test_execution_failure_is_captured(orchestrator, monkeypatch):
    def failing_execution(*args, **kwargs):
        raise RuntimeError("Tool execution failed")

    monkeypatch.setattr(
        orchestrator,
        "_execute_registered_tool",
        failing_execution,
    )

    request = ExecutionRequest(
        tool_id="ndvi",
        input_references=["image_001.tif"],
    )

    result = orchestrator.execute(request)

    assert result.status == "failed"
    assert result.error == "Tool execution failed"


def test_invalid_request_type(orchestrator):
    with pytest.raises(TypeError):
        orchestrator.execute("invalid")


def test_execution_output_carries_the_real_result(
    orchestrator, sentinel2_scene, tmp_path
):
    request = ExecutionRequest(
        tool_id="ndvi",
        parameters={
            "red_band": "B4",
            "nir_band": "B8",
        },
        input_references=[sentinel2_scene],
        output_directory=str(tmp_path / "outputs"),
    )

    result = orchestrator.execute(request)

    assert result.status == "completed"
    assert result.output["tool_id"] == "ndvi"
    assert result.output["result_type"] == "raster_index"
    assert result.output["data"]["formula"] == "(B8 - B4) / (B8 + B4)"
    assert result.output["statistics"]["mean"] == pytest.approx(0.2)


# ============================================================
# REGISTRY POLICY ENFORCED BEFORE EXECUTION
# ============================================================
def test_too_many_inputs_are_blocked(orchestrator, sentinel2_scene):
    # NDVI declares max_images = 1 in the registry.
    request = ExecutionRequest(
        tool_id="ndvi",
        input_references=[sentinel2_scene, sentinel2_scene],
    )

    result = orchestrator.execute(request)

    assert result.status == "blocked"
    assert "between 1 and 1" in result.error


def test_too_few_inputs_are_blocked(orchestrator, sentinel2_scene):
    # Change detection declares min_images = 2.
    request = ExecutionRequest(
        tool_id="change_detection",
        input_references=[sentinel2_scene],
    )

    result = orchestrator.execute(request)

    assert result.status == "blocked"
    assert "between 2 and 2" in result.error


def test_registered_tool_without_an_implementation_is_blocked(
    orchestrator, sentinel2_scene
):
    # The tool is a legitimate registry entry, but nothing is bound to it yet.
    # It must report that honestly rather than return a placeholder result.
    request = ExecutionRequest(
        tool_id="satellite_vqa",
        input_references=[sentinel2_scene],
    )

    result = orchestrator.execute(request)

    assert result.status == "blocked"
    assert "no execution implementation" in result.error
    assert result.output is None


def test_a_failing_tool_reports_the_underlying_reason(orchestrator, tmp_path):
    request = ExecutionRequest(
        tool_id="ndvi",
        input_references=[str(tmp_path / "does_not_exist.tif")],
    )

    result = orchestrator.execute(request)

    assert result.status == "failed"
    assert "not found" in result.error
