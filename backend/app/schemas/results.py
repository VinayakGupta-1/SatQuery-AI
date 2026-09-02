from typing import Any

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str
    description: str
    confidence: float | None = None


class TaskResult(BaseModel):
    result_type: str
    data: Any

    confidence: float | None = None

    evidence: list[Evidence] = Field(
        default_factory=list
    )


class ExecutionSummary(BaseModel):
    steps: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)


class FinalResult(BaseModel):
    task_id: str
    answer: str

    results: list[TaskResult] = Field(
        default_factory=list
    )

    confidence: float | None = None

    evidence: list[Evidence] = Field(
        default_factory=list
    )

    execution_summary: ExecutionSummary