from app.schemas.errors import ValidationResult
from app.schemas.inputs import ImageInput
from app.schemas.task import InputRequirements


class InputValidator:

    def validate(
        self,
        inputs: list[ImageInput],
        requirements: InputRequirements,
    ) -> ValidationResult:
        """
        Validate user-provided inputs against task requirements.

        This validator is deterministic:
        it does not use an LLM or make semantic guesses.
        """
        raise NotImplementedError
