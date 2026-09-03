from app.schemas.errors import ErrorCode, ValidationIssue, ValidationResult
from app.schemas.inputs import ImageInput
from app.schemas.task import InputRequirements
from app.tools.raster.bands import canonical_name, normalise


def _band_key(name: str) -> str:
    """Reduce a band name to a form that can be compared across vocabularies.

    A requirement for "swir" and an image reporting "swir1" name the same
    band, as do "red" and "B4". Comparing the raw strings would reject valid
    imagery, so both sides are reduced to their canonical logical name first.
    Names with no known mapping fall back to a normalised literal comparison,
    which keeps unknown bands checkable rather than silently accepted.
    """
    return canonical_name(name) or normalise(name)


def validate_inputs(
    images: list[ImageInput],
    requirements: InputRequirements,
) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[str] = []

    # 1. Image count validation
    image_count = len(images)
    if image_count < requirements.min_images:
        errors.append(ValidationIssue(
            code=ErrorCode.INVALID_IMAGE_COUNT,
            message=(f"Expected at least {requirements.min_images} image(s), "
                     f"but received {image_count}."),
            field="images",
        ))
    if requirements.max_images > 0 and image_count > requirements.max_images:
        errors.append(ValidationIssue(
            code=ErrorCode.INVALID_IMAGE_COUNT,
            message=(f"Expected at most {requirements.max_images} image(s), "
                     f"but received {image_count}."),
            field="images",
        ))

    # 2. Metadata validation
    if requirements.requires_metadata:
        for image in images:
            if image.metadata is None:
                errors.append(ValidationIssue(
                    code=ErrorCode.MISSING_INPUT,
                    message=f"Metadata is required for image '{image.id}'.",
                    field=f"images.{image.id}.metadata",
                ))

    # 3. Modality validation
    if requirements.required_modalities:
        for image in images:
            if image.metadata is None:
                errors.append(ValidationIssue(
                    code=ErrorCode.MISSING_INPUT,
                    message=("Metadata is required to determine the "
                             f"modality of image '{image.id}'."),
                    field=f"images.{image.id}.metadata",
                ))
            elif image.metadata.modality not in requirements.required_modalities:
                errors.append(ValidationIssue(
                    code=ErrorCode.MODALITY_MISMATCH,
                    message=(f"Image '{image.id}' has modality "
                             f"'{image.metadata.modality}', but one of "
                             f"{requirements.required_modalities} is required."),
                    field=f"images.{image.id}.metadata.modality",
                ))

    # 4. Temporal information validation
    if requirements.requires_temporal_information:
        for image in images:
            if image.metadata is None or image.metadata.acquisition_date is None:
                errors.append(ValidationIssue(
                    code=ErrorCode.TEMPORAL_METADATA_MISSING,
                    message=f"Acquisition date is required for image '{image.id}'.",
                    field=f"images.{image.id}.metadata.acquisition_date",
                ))

    # 5. CRS validation
    if requirements.requires_crs or requirements.requires_georeferencing:
        for image in images:
            if image.metadata is None or image.metadata.crs is None:
                errors.append(ValidationIssue(
                    code=ErrorCode.CRS_MISMATCH,
                    message=f"CRS information is required for image '{image.id}'.",
                    field=f"images.{image.id}.metadata.crs",
                ))

    # 6. Required spectral bands validation
    if requirements.required_bands:
        required_bands = {_band_key(band): band for band in requirements.required_bands}
        for image in images:
            if image.metadata is None:
                errors.append(ValidationIssue(
                    code=ErrorCode.MISSING_INPUT,
                    message=f"Metadata is required to validate bands for image '{image.id}'.",
                    field=f"images.{image.id}.metadata",
                ))
                continue
            available_bands = {_band_key(band) for band in image.metadata.bands}
            missing_bands = sorted(
                name
                for key, name in required_bands.items()
                if key not in available_bands
            )
            if missing_bands:
                errors.append(ValidationIssue(
                    code=ErrorCode.INVALID_PARAMETER,
                    message=(f"Image '{image.id}' is missing required band(s): "
                             f"{missing_bands}."),
                    field=f"images.{image.id}.metadata.bands",
                ))

    # 7. Optical and SAR input validation
    for image in images:
        modality = image.metadata.modality if image.metadata else None
        if requirements.requires_optical_input and modality != "optical":
            errors.append(ValidationIssue(
                code=ErrorCode.MODALITY_MISMATCH,
                message=f"Image '{image.id}' must be optical.",
                field=f"images.{image.id}.metadata.modality",
            ))
        if requirements.requires_sar_input and modality != "sar":
            errors.append(ValidationIssue(
                code=ErrorCode.MODALITY_MISMATCH,
                message=f"Image '{image.id}' must be SAR.",
                field=f"images.{image.id}.metadata.modality",
            ))

    # 8. Temporal pair validation
    if requirements.requires_temporal_pair:
        if image_count != 2:
            errors.append(ValidationIssue(
                code=ErrorCode.INVALID_IMAGE_COUNT,
                message="A temporal pair requires exactly two images.",
                field="images",
            ))
        else:
            dates = [image.metadata.acquisition_date if image.metadata else None
                     for image in images]
            if any(date is None for date in dates):
                errors.append(ValidationIssue(
                    code=ErrorCode.TEMPORAL_METADATA_MISSING,
                    message="A temporal pair requires acquisition dates for both images.",
                    field="images",
                ))
            elif dates[0] == dates[1]:
                errors.append(ValidationIssue(
                    code=ErrorCode.TEMPORAL_INCOMPATIBILITY,
                    message="Temporal pair images must be acquired at different times.",
                    field="images",
                ))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
