"""Task endpoints -- submit a query with imagery and get an answer back."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.ingestion import (
    IngestionError,
    assemble_scene,
    describe_upload,
    store_upload,
)
from app.api.responses import (
    build_task_response,
    build_validation_response,
    collect_artifacts,
)
from app.api.schemas import ImageSummary, TaskListEntry, TaskResponse, ValidationResponse
from app.api.store import TaskRecord, task_store
from app.config.settings import get_settings
from app.controller.pipeline import SatQueryPipeline
from app.schemas.inputs import ImageInput

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

pipeline = SatQueryPipeline()


def _parse_parameters(raw: str | None) -> dict[str, Any]:
    """Parse the optional user-supplied parameter JSON object."""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HTTPException(400, f"'parameters' is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise HTTPException(400, "'parameters' must be a JSON object.")
    return parsed


async def _ingest(
    files: list[UploadFile],
    task_id: str,
    as_scene: bool = False,
    sensor: str | None = None,
) -> tuple[list[ImageInput], list[ImageSummary]]:
    """Store and describe every upload, or fail with a clear message.

    With ``as_scene`` the uploads are treated as bands of one image, which is
    how real products arrive -- one file per band, possibly at different
    resolutions. Otherwise each file is a separate image.
    """
    settings = get_settings()

    if not files:
        raise HTTPException(400, "At least one raster file is required.")
    if not as_scene and len(files) > settings.max_images_per_task:
        raise HTTPException(
            400,
            f"{len(files)} files were supplied; at most "
            f"{settings.max_images_per_task} are accepted per task.",
        )

    stored: list[tuple[str, str]] = []
    for upload in files:
        try:
            content = await upload.read()
            stored.append(
                store_upload(content, upload.filename, task_id, settings)
            )
        except IngestionError as error:
            raise HTTPException(400, str(error)) from error
        finally:
            await upload.close()

    try:
        if as_scene:
            manifest = assemble_scene(stored, task_id, settings, sensor)
            image, summary = describe_upload(
                manifest,
                "scene_1",
                f"{len(stored)}-band scene",
            )
            return [image], [summary]

        images: list[ImageInput] = []
        summaries: list[ImageSummary] = []
        for index, (path, display) in enumerate(stored, start=1):
            image, summary = describe_upload(path, f"image_{index}", display)
            images.append(image)
            summaries.append(summary)
        return images, summaries
    except IngestionError as error:
        raise HTTPException(400, str(error)) from error


@router.post("", response_model=TaskResponse)
async def create_task(
    query: str = Form(..., description="The natural-language request."),
    files: list[UploadFile] = File(..., description="One or more raster files."),
    parameters: str | None = Form(
        None, description="Optional JSON object of explicit tool parameters."
    ),
    as_scene: bool = Form(
        False,
        description=(
            "Treat the uploaded files as bands of a single scene rather than "
            "as separate images. Real products ship one file per band."
        ),
    ),
    sensor: str | None = Form(
        None, description="Sensor name, e.g. 'sentinel2'. Disambiguates band numbers."
    ),
) -> TaskResponse:
    """Run a natural-language query against uploaded imagery.

    A task that is rejected by the validator or blocked by the registry still
    returns 200 with the full explanation: that is a completed analysis whose
    answer is "no", not a transport-level failure.
    """
    if not query or not query.strip():
        raise HTTPException(400, "A query is required.")

    task_id = f"task_{uuid.uuid4().hex[:12]}"
    user_parameters = _parse_parameters(parameters)
    images, summaries = await _ingest(files, task_id, as_scene, sensor)

    settings = get_settings()
    run = pipeline.run(
        query=query.strip(),
        images=images,
        task_id=task_id,
        output_directory=settings.task_output_directory(task_id),
        user_parameters=user_parameters or None,
    )

    artifacts = collect_artifacts(run)
    task_store.save(
        TaskRecord(
            run=run,
            images=summaries,
            artifacts={
                artifact_id: artifact["path"]
                for artifact_id, artifact in artifacts.items()
            },
        )
    )
    return build_task_response(run, summaries, artifacts)


@router.post("/validate", response_model=ValidationResponse)
async def validate_task(
    query: str = Form(...),
    files: list[UploadFile] = File(...),
    as_scene: bool = Form(False),
    sensor: str | None = Form(None),
) -> ValidationResponse:
    """Check whether a query and imagery would run, without executing anything.

    Useful for a frontend that wants to tell the user their upload is wrong
    before committing to a long computation.
    """
    if not query or not query.strip():
        raise HTTPException(400, "A query is required.")

    task_id = f"check_{uuid.uuid4().hex[:12]}"
    images, summaries = await _ingest(files, task_id, as_scene, sensor)

    # Running the pipeline with no output directory still stops at validation
    # whenever the inputs are wrong; when they are right we discard the run
    # rather than execute, by asking only for the dry-run response.
    run = pipeline.run(query=query.strip(), images=images, task_id=task_id)
    return build_validation_response(run, summaries)


@router.get("", response_model=list[TaskListEntry])
def list_tasks(limit: int = 50) -> list[TaskListEntry]:
    """List recent tasks, newest first."""
    return [
        TaskListEntry(
            task_id=record.run.task_id,
            query=record.run.query,
            outcome=record.run.outcome,
            answer=record.run.final.answer,
        )
        for record in task_store.list(limit=max(1, min(limit, 200)))
    ]


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str) -> TaskResponse:
    """Retrieve a task that has already run."""
    record = task_store.get(task_id)
    if record is None:
        raise HTTPException(404, f"No task with id '{task_id}'.")
    return build_task_response(record.run, record.images, collect_artifacts(record.run))


@router.get("/{task_id}/artifacts/{artifact_id}")
def download_artifact(task_id: str, artifact_id: str) -> FileResponse:
    """Download a raster a task produced.

    Only paths recorded on the task are served, so an arbitrary path can never
    be requested through this endpoint.
    """
    record = task_store.get(task_id)
    if record is None:
        raise HTTPException(404, f"No task with id '{task_id}'.")

    path = record.artifacts.get(artifact_id)
    if path is None:
        raise HTTPException(404, f"Task '{task_id}' has no artifact '{artifact_id}'.")
    if not os.path.exists(path):
        raise HTTPException(410, f"Artifact '{artifact_id}' is no longer on disk.")

    return FileResponse(
        path, media_type="image/tiff", filename=os.path.basename(path)
    )
