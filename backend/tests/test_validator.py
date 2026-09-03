from datetime import date

from app.schemas.inputs import ImageInput, ImageMetadata
from app.schemas.task import InputRequirements
from app.validator.validator import validate_inputs


def test_valid_single_image():
    image = ImageInput(
        id="img1",
        path="test.jpg",
        metadata=ImageMetadata(
            acquisition_date=date(2026, 1, 1),
            modality="optical",
            crs="EPSG:4326",
        ),
    )

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        required_modalities=["optical"],
        requires_metadata=True,
        requires_crs=True,
        requires_temporal_information=True,
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is True
    assert len(result.errors) == 0


def test_invalid_image_count():
    requirements = InputRequirements(
        min_images=2,
        max_images=2,
    )

    result = validate_inputs(
        images=[],
        requirements=requirements,
    )

    assert result.valid is False
    assert len(result.errors) == 1


def test_missing_metadata():
    image = ImageInput(
        id="img1",
        path="test.jpg",
    )

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        requires_metadata=True,
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is False
    assert any(
        error.code.value == "MISSING_INPUT"
        for error in result.errors
    )


def test_modality_mismatch():
    image = ImageInput(
        id="img1",
        path="test.jpg",
        metadata=ImageMetadata(
            modality="sar",
        ),
    )

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        required_modalities=["optical"],
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is False
    assert any(
        error.code.value == "MODALITY_MISMATCH"
        for error in result.errors
    )


def test_missing_temporal_information():
    image = ImageInput(
        id="img1",
        path="test.jpg",
        metadata=ImageMetadata(
            modality="optical",
        ),
    )

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        requires_temporal_information=True,
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is False
    assert any(
        error.code.value == "TEMPORAL_METADATA_MISSING"
        for error in result.errors
    )

def test_too_many_images():
    images = [
        ImageInput(id="img1", path="1.jpg"),
        ImageInput(id="img2", path="2.jpg"),
    ]

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
    )

    result = validate_inputs(
        images=images,
        requirements=requirements,
    )

    assert result.valid is False
    assert any(
        error.code.value == "INVALID_IMAGE_COUNT"
        for error in result.errors
    )


def test_missing_metadata_with_modality_requirement():
    image = ImageInput(
        id="img1",
        path="test.jpg",
    )

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        required_modalities=["optical"],
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is False
    assert any(
        error.code.value == "MISSING_INPUT"
        for error in result.errors
    )


def test_missing_acquisition_date():
    image = ImageInput(
        id="img1",
        path="test.jpg",
        metadata=ImageMetadata(
            modality="optical",
        ),
    )

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        requires_temporal_information=True,
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is False
    assert any(
        error.code.value == "TEMPORAL_METADATA_MISSING"
        for error in result.errors
    )


def test_valid_complete_input():
    image = ImageInput(
        id="img1",
        path="test.jpg",
        metadata=ImageMetadata(
            acquisition_date=date(2026, 1, 1),
            modality="optical",
            crs="EPSG:4326",
        ),
    )

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        required_modalities=["optical"],
        requires_metadata=True,
        requires_temporal_information=True,
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is True
    assert len(result.errors) == 0


def test_multiple_validation_errors():
    image = ImageInput(
        id="img1",
        path="test.jpg",
        metadata=ImageMetadata(
            modality="sar",
        ),
    )

    requirements = InputRequirements(
        min_images=2,
        max_images=2,
        required_modalities=["optical"],
        requires_temporal_information=True,
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is False
    assert len(result.errors) >= 2

def test_missing_crs():
    image = ImageInput(
        id="img1",
        path="test.jpg",
        metadata=ImageMetadata(
            acquisition_date=date(2026, 1, 1),
            modality="optical",
        ),
    )

    requirements = InputRequirements(
        min_images=1,
        max_images=1,
        requires_crs=True,
    )

    result = validate_inputs(
        images=[image],
        requirements=requirements,
    )

    assert result.valid is False
    assert any(
        error.code.value == "CRS_MISMATCH"
        for error in result.errors
    )