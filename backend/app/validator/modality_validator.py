from app.schemas.inputs import ImageInput
from app.schemas.task import InputRequirements
from app.schemas.errors import (
    ErrorCode,
    ValidationIssue,
)


def validate_modality(
    images: list[ImageInput],
    requirements: InputRequirements,
) -> list[ValidationIssue]:

    issues = []

    if not requirements.required_modalities:
        return issues

    for image in images:

        if image.metadata is None or image.metadata.modality is None:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.MISSING_INPUT,
                    message=(
                        f"Modality is missing for image '{image.id}'."
                    ),
                    field=f"image.{image.id}.modality",
                )
            )
            continue

        if image.modality not in requirements.required_modalities:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.MODALITY_MISMATCH,
                    message=(
                        f"Image '{image.id}' has modality "
                        f"'{image.modality}', but the task requires "
                        f"one of: "
                        f"{requirements.required_modalities}."
                    ),
                    field=f"image.{image.id}.metadata.modality",
                )
            )

    return issues
