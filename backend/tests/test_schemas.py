from datetime import date

from pydantic import ValidationError

from app.schemas.inputs import ImageInput, ImageMetadata
from app.schemas.task import (
    InputReference,
    InputRequirements,
    SatQueryTask,
    TaskType,
)
from app.schemas.errors import (
    ErrorCode,
    ValidationIssue,
    ValidationResult,
)
from app.schemas.results import (
    Evidence,
    ExecutionSummary,
    FinalResult,
    TaskResult,
)


def test_image_input():
    metadata = ImageMetadata(
        acquisition_date=date(2026, 1, 15),
        modality="optical",
        sensor="Sentinel-2",
        crs="EPSG:4326",
        width=1024,
        height=1024,
        bands=["red", "green", "blue", "nir"],
    )

    image = ImageInput(
        id="img_001",
        path="data/image.tif",
        metadata=metadata,
    )

    assert image.id == "img_001"
    assert image.metadata.modality == "optical"
    assert "nir" in image.metadata.bands


def test_satquery_task():
    task = SatQueryTask(
        task_id="task_001",
        query="Calculate NDVI",
        task_type=TaskType.UNKNOWN,
    )

    assert task.task_id == "task_001"
    assert task.query == "Calculate NDVI"
    assert task.task_type == TaskType.UNKNOWN


def test_input_requirements():
    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        required_modalities=["optical"],
        required_bands=["red", "nir"],
        requires_metadata=True,
        requires_crs=True,
    )

    assert requirements.min_images == 1
    assert "nir" in requirements.required_bands
    assert requirements.requires_metadata is True


def test_validation_result():
    issue = ValidationIssue(
        code=ErrorCode.MISSING_INPUT,
        message="Required image input is missing.",
        field="inputs",
    )

    result = ValidationResult(
        valid=False,
        errors=[issue],
    )

    assert result.valid is False
    assert result.errors[0].code == ErrorCode.MISSING_INPUT


def test_final_result():
    evidence = Evidence(
        source="sentinel-2",
        description="Satellite imagery used for analysis.",
        confidence=0.95,
    )

    task_result = TaskResult(
        result_type="analysis",
        data={"value": 0.72},
        confidence=0.92,
        evidence=[evidence],
    )

    summary = ExecutionSummary(
        steps=["validate_input", "execute_analysis"],
        tools_used=["ndvi_tool"],
    )

    result = FinalResult(
        task_id="task_001",
        answer="NDVI analysis completed.",
        results=[task_result],
        confidence=0.92,
        evidence=[evidence],
        execution_summary=summary,
    )

    assert result.task_id == "task_001"
    assert result.results[0].data["value"] == 0.72
    assert "ndvi_tool" in result.execution_summary.tools_used