from app.schemas.inputs import ImageInput
from app.schemas.task import InputRequirements
from app.schemas.errors import (
    ErrorCode,
    ValidationIssue,
    ValidationResult,
)

from app.validator.image_validator import validate_image
from app.validator.metadata_validator import validate_metadata
from app.validator.modality_validator import validate_modality
from app.validator.temporal_validator import validate_temporal


def validate_inputs(
    images: list[ImageInput],
    requirements: InputRequirements,
) -> ValidationResult:

    issues: list[ValidationIssue] = []

    # 1. Validate image count
    image_count = len(images)

    if image_count < requirements.min_images:
        issues.append(
            ValidationIssue(
                code=ErrorCode.INVALID_IMAGE_COUNT,
                message=(
                    f"At least {requirements.min_images} image(s) "
                    f"are required, but {image_count} were provided."
                ),
                field="images",
            )
        )

    if (
        requirements.max_images > 0
        and image_count > requirements.max_images
    ):
        issues.append(
            ValidationIssue(
                code=ErrorCode.INVALID_IMAGE_COUNT,
                message=(
                    f"At most {requirements.max_images} image(s) "
                    f"are allowed, but {image_count} were provided."
                ),
                field="images",
            )
        )

    # 2. Validate image properties
    issues.extend(validate_image(images, requirements))

    # 3. Validate metadata
    issues.extend(validate_metadata(images, requirements))

    # 4. Validate modality
    issues.extend(validate_modality(images, requirements))

    # 5. Validate temporal information
    issues.extend(validate_temporal(images, requirements))

    return ValidationResult(
        valid=len(issues) == 0,
        errors=issues,
    )
