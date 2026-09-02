from app.schemas.inputs import ImageInput
from app.schemas.task import InputRequirements
from app.schemas.errors import (
    ErrorCode,
    ValidationIssue,
)


def validate_temporal(
    images: list[ImageInput],
    requirements: InputRequirements,
) -> list[ValidationIssue]:

    issues = []

    if not requirements.requires_temporal_information:
        return issues

    for image in images:

        if image.metadata is None:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.TEMPORAL_METADATA_MISSING,
                    message=(
                        f"Temporal metadata is missing "
                        f"for image '{image.id}'."
                    ),
                    field=f"image.{image.id}.metadata",
                )
            )
            continue

        if not image.metadata.acquisition_date:
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