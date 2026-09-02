from app.schemas.inputs import ImageInput
from app.schemas.task import InputRequirements
from app.schemas.errors import (
    ErrorCode,
    ValidationIssue,
)


def validate_metadata(
    images: list[ImageInput],
    requirements: InputRequirements,
) -> list[ValidationIssue]:

    issues = []

    for image in images:

        metadata = image.metadata

        if requirements.requires_metadata and metadata is None:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.MISSING_INPUT,
                    message=(
                        f"Metadata is required for image '{image.id}'."
                    ),
                    field=f"image.{image.id}.metadata",
                )
            )
            continue

        if metadata is None:
            continue

        if requirements.requires_georeferencing:
            if not metadata.crs:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.CRS_MISMATCH,
                        message=(
                            f"Georeferencing/CRS information is missing "
                            f"for image '{image.id}'."
                        ),
                        field=f"image.{image.id}.metadata.crs",
                    )
                )

        if requirements.requires_crs and not metadata.crs:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.CRS_MISMATCH,
                    message=(
                        f"CRS is required for image '{image.id}'."
                    ),
                    field=f"image.{image.id}.metadata.crs",
                )
            )

        if requirements.requires_temporal_information:
            if not metadata.acquisition_date:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.TEMPORAL_METADATA_MISSING,
                        message=(
                            f"Acquisition date is missing "
                            f"for image '{image.id}'."
                        ),
                        field=(
                            f"image.{image.id}."
                            "metadata.acquisition_date"
                        ),
                    )
                )

    return issues
