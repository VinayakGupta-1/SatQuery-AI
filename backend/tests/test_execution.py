import pytest

from app.controller.execution.orchestrator import (
    ExecutionOrchestrator,
    ExecutionRequest,
    ExecutionResult,
)


@pytest.fixture
def orchestrator():
    return ExecutionOrchestrator()


def test_valid_execution(orchestrator):
    request = ExecutionRequest(
        tool_id="ndvi",
        parameters={},
        input_references=["image_001.tif"],
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


def test_execution_metadata(orchestrator):
    request = ExecutionRequest(
        tool_id="ndvi",
        input_references=[
            "image_001.tif",
            "image_002.tif",
        ],
    )

    result = orchestrator.execute(request)

    assert result.status == "completed"
    assert result.execution_metadata["tool_name"] == "NDVI"
    assert result.execution_metadata["input_count"] == 2


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


def test_execution_output_contains_request_data(orchestrator):
    request = ExecutionRequest(
        tool_id="ndvi",
        parameters={
            "red_band": "B4",
            "nir_band": "B8",
        },
        input_references=["image_001.tif"],
    )

    # NDVI currently has these parameters registered.
    result = orchestrator.execute(request)

    assert result.status == "completed"
    assert result.output["tool_id"] == "ndvi"
    assert result.output["parameters"]["red_band"] == "B4"
    assert result.output["parameters"]["nir_band"] == "B8"
