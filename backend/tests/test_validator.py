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

# ============================================================
# BAND NAMES ARE COMPARED ACROSS VOCABULARIES
# ============================================================
def _optical(bands):
    return ImageInput(
        id="img1",
        path="scene.tif",
        metadata=ImageMetadata(modality="optical", crs="EPSG:32643", bands=bands),
    )


def test_band_synonyms_satisfy_a_requirement():
    # "swir" and "swir1" name the same band, as do "red" and "B4". Comparing
    # the raw strings would reject imagery that is actually suitable.
    result = validate_inputs(
        images=[_optical(["nir", "swir1"])],
        requirements=InputRequirements(min_images=1, required_bands=["nir", "swir"]),
    )

    assert result.valid


def test_sensor_band_identifiers_satisfy_a_logical_requirement():
    result = validate_inputs(
        images=[_optical(["B4", "B8"])],
        requirements=InputRequirements(min_images=1, required_bands=["red", "nir"]),
    )

    assert result.valid


def test_a_genuinely_absent_band_is_still_rejected():
    result = validate_inputs(
        images=[_optical(["red", "green"])],
        requirements=InputRequirements(min_images=1, required_bands=["red", "nir"]),
    )

    assert not result.valid
    # The message names the band the caller asked for, not an internal alias.
    assert "'nir'" in result.errors[0].message


def test_unknown_band_names_are_compared_literally():
    # A band with no known mapping must still be checkable, not waved through.
    matching = validate_inputs(
        images=[_optical(["polarisation_xy"])],
        requirements=InputRequirements(min_images=1, required_bands=["polarisation_xy"]),
    )
    missing = validate_inputs(
        images=[_optical(["polarisation_xy"])],
        requirements=InputRequirements(min_images=1, required_bands=["polarisation_zz"]),
    )

    assert matching.valid
    assert not missing.valid
