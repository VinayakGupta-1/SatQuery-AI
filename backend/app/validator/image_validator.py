from app.schemas.inputs import ImageInput
from app.schemas.task import InputRequirements
from app.schemas.errors import (
    ErrorCode,
    ValidationIssue,
)

def validate_image(
    images: list[ImageInput],
    requirements: InputRequirements
)-> list[ValidationIssue]:
    issues = []
    for image in images:
        if not image.path:
            issues.append(
                ValidationIssue(
                    code = ErrorCode.MISSING_INPUT,
                    message=(
                        f"Image path is missing for "
                        f"image '{image.id}'."
                    ),
                    field = f"image.{image.id}.path",
                )
            )
    return issues
