"""Task endpoints -- submit a query with imagery and get an answer back."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.acquisition import acquire as acquire_imagery
from app.api import history
from app.api.auth import current_user
from app.api.ingestion import (
    IngestionError,
    safe_filename,
    assemble_scene,
    describe_upload,
    store_upload,
)
from app.api.responses import (
    build_task_response,
    build_validation_response,
    collect_artifacts,
)
from app.api.schemas import (
    ImageSummary,
    TaskListEntry,
    TaskResponse,
    TaskStatus,
    ValidationResponse,
)
from app.api.progress import CLIENT_REF, progress_store
from app.api.store import TaskRecord, task_store
from app.auth import User
from app.config.settings import get_settings
from app.controller.pipeline import ImageryAcquirer, SatQueryPipeline
from app.controller.task_understanding.task_understanding import TaskUnderstandingResult
from app.schemas.acquisition import AcquisitionReport
from app.storage.artifacts import get_artifact_store
from app.schemas.inputs import ImageInput

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

pipeline = SatQueryPipeline()

#: Longest question accepted. A question is a sentence; anything far longer is
#: a paste error or abuse, and the text may be forwarded to a hosted model.
MAX_QUERY_CHARS = 2000
#: Longest location accepted. It may be forwarded to the geocoder.
MAX_LOCATION_CHARS = 200
#: Uploads are read in pieces of this size, so an oversized file is refused as
#: soon as it crosses the limit rather than after it is entirely in memory.
UPLOAD_CHUNK_BYTES = 1024 * 1024

#: Content types for the files tools write. Anything else is served as bytes.
ARTIFACT_MEDIA_TYPES = {
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".png": "image/png",
}


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


def _check_query(query: str | None) -> str:
    """The trimmed question, or a 400 explaining what is wrong with it."""
    if not query or not query.strip():
        raise HTTPException(400, "A query is required.")
    query = query.strip()
    if len(query) > MAX_QUERY_CHARS:
        raise HTTPException(
            400, f"The question is {len(query):,} characters; at most {MAX_QUERY_CHARS:,} are accepted."
        )
    return query


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read an upload, refusing it as soon as it exceeds ``limit`` bytes."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise IngestionError(
                f"'{safe_filename(upload.filename)}' is larger than the "
                f"{limit:,} byte limit."
            )
        chunks.append(chunk)


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

    A rejected upload takes the whole task's files with it: when the third of
    three files fails, the first two would otherwise stay on disk forever,
    belonging to a task that was never recorded.
    """
    try:
        return await _ingest_files(files, task_id, as_scene, sensor)
    except HTTPException:
        get_artifact_store().delete_task(task_id)
        raise


async def _ingest_files(
    files: list[UploadFile],
    task_id: str,
    as_scene: bool,
    sensor: str | None,
) -> tuple[list[ImageInput], list[ImageSummary]]:
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
            content = await _read_limited(upload, settings.max_upload_bytes)
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


def _fetcher(
    task_id: str,
    location: str | None,
    summaries: list[ImageSummary],
    progress: Callable[[str], None] | None = None,
) -> ImageryAcquirer:
    """An acquirer that fetches into the task's upload directory.

    Each fetched file is then described by the same code that describes an
    upload, so its band names, sensor and date are read from the file rather
    than taken on trust from the fetcher.
    """

    def fetch(understanding: TaskUnderstandingResult) -> tuple[list[ImageInput], AcquisitionReport]:
        outcome = acquire_imagery(
            understanding,
            location,
            get_artifact_store().upload_directory(task_id),
            progress=progress,
        )
        images: list[ImageInput] = []
        for fetched in outcome.images:
            try:
                image, summary = describe_upload(
                    fetched.path, fetched.scene.image_id, fetched.display_name
                )
            except IngestionError as error:
                report = outcome.report.model_copy(
                    update={"status": "failed", "message": str(error), "scenes": []}
                )
                summaries.clear()
                return [], report
            images.append(image)
            summaries.append(summary)
        return images, outcome.report

    return fetch


@router.post("", response_model=TaskResponse)
async def create_task(
    query: str = Form(..., description="The natural-language request."),
    files: list[UploadFile] | None = File(
        None,
        description=(
            "One or more raster files. Leave out to have SatQuery fetch Sentinel "
            "imagery for the place the question (or `location`) names."
        ),
    ),
    location: str | None = Form(
        None,
        description=(
            "Where to fetch imagery when no files are sent: a place name, "
            "'lat, lon', or 'west, south, east, north'. Overrides any place in "
            "the question."
        ),
    ),
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
    client_ref: str | None = Form(
        None,
        description=(
            "A random reference chosen by the client. While the request runs, "
            "GET /api/progress/{client_ref} reports the stage it has reached."
        ),
    ),
    user: User | None = Depends(current_user),
) -> TaskResponse:
    """Run a natural-language query against uploaded or fetched imagery.

    A task that is rejected by the validator or blocked by the registry still
    returns 200 with the full explanation: that is a completed analysis whose
    answer is "no", not a transport-level failure. The same holds when no
    imagery was sent and none could be fetched -- the answer says why.
    """
    query = _check_query(query)
    if location is not None and len(location.strip()) > MAX_LOCATION_CHARS:
        raise HTTPException(
            400, f"The location is longer than {MAX_LOCATION_CHARS} characters."
        )

    settings = get_settings()
    files = [upload for upload in files or [] if upload.filename]
    if not files and not settings.fetch_enabled:
        raise HTTPException(
            400,
            "At least one raster file is required: automatic imagery fetching is "
            "turned off on this server.",
        )

    task_id = f"task_{uuid.uuid4().hex[:12]}"
    user_parameters = _parse_parameters(parameters)
    owner = user.id if user else None
    ref = client_ref if client_ref and CLIENT_REF.match(client_ref) else None

    def on_stage(stage: str, status: str, detail: str = "") -> None:
        if ref:
            progress_store.report(ref, owner, stage, status, detail)

    summaries: list[ImageSummary] = []
    acquire: ImageryAcquirer | None = None
    if files:
        images, summaries = await _ingest(files, task_id, as_scene, sensor)
    else:
        images = []
        acquire = _fetcher(
            task_id, location, summaries,
            progress=lambda detail: on_stage("acquisition", "running", detail),
        )

    # Off the event loop: a fetch waits on the network for tens of seconds,
    # and the server must keep answering other requests meanwhile.
    run = await run_in_threadpool(
        pipeline.run,
        query=query,
        images=images,
        task_id=task_id,
        output_directory=get_artifact_store().output_directory(task_id),
        user_parameters=user_parameters or None,
        acquire=acquire,
        on_stage=on_stage,
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
            user_id=owner,
        )
    )
    response = build_task_response(run, summaries, artifacts)
    if user is not None:
        # Kept per user in Supabase, so the result outlives this process.
        await run_in_threadpool(history.save, user, response.model_dump(mode="json"))
    if ref:
        progress_store.report(ref, owner, "result_integration", "done", "", done=True)
    return response


@router.post("/validate", response_model=ValidationResponse)
async def validate_task(
    query: str = Form(...),
    files: list[UploadFile] | None = File(None),
    as_scene: bool = Form(False),
    sensor: str | None = Form(None),
    user: User | None = Depends(current_user),
) -> ValidationResponse:
    """Check whether a query and imagery would run, without executing anything.

    Useful for a frontend that wants to tell the user their upload is wrong
    before committing to a long computation.
    """
    query = _check_query(query)
    files = [upload for upload in files or [] if upload.filename]
    if not files:
        # A dry run must not download anything; fetched imagery is checked by
        # the same validator when the analysis itself runs.
        raise HTTPException(
            400,
            "Checking needs attached imagery. Without an attachment, ask the "
            "question directly: SatQuery fetches a scene and validates it then.",
        )

    task_id = f"check_{uuid.uuid4().hex[:12]}"
    images, summaries = await _ingest(files, task_id, as_scene, sensor)

    # Every stage runs, including the Registry's execution policy, and then
    # the pipeline stops short of calling the tool. The uploads were only
    # needed to read their metadata, and no task is recorded that could refer
    # to them later, so they are removed rather than left to accumulate.
    try:
        run = pipeline.run(
            query=query, images=images, task_id=task_id, execute=False
        )
        return build_validation_response(run, summaries)
    finally:
        get_artifact_store().delete_task(task_id)


@router.get("", response_model=list[TaskListEntry])
def list_tasks(limit: int = 50, user: User | None = Depends(current_user)) -> list[TaskListEntry]:
    """List the caller's recent tasks, newest first.

    Signed-in users get their stored history, which survives restarts; if
    the history service is unreachable, the tasks this process remembers.
    """
    limit = max(1, min(limit, 200))
    if user is not None:
        try:
            return [
                TaskListEntry(
                    task_id=row["id"],
                    query=row["query"],
                    status=TaskStatus(row["status"]),
                    outcome=row["outcome"],
                    answer=row["answer"],
                )
                for row in history.recent(user, limit)
            ]
        except history.HistoryUnavailable:
            pass
    owner = user.id if user else None
    return [
        TaskListEntry(
            task_id=record.run.task_id,
            query=record.run.query,
            status=TaskStatus(record.run.status),
            outcome=record.run.outcome,
            answer=record.run.final.answer,
        )
        for record in task_store.list(limit=200)
        if record.user_id == owner
    ][:limit]


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, user: User | None = Depends(current_user)) -> TaskResponse:
    """Retrieve a task that has already run -- only the caller's own."""
    record = task_store.get(task_id)
    owner = user.id if user else None
    if record is not None and record.user_id == owner:
        return build_task_response(record.run, record.images, collect_artifacts(record.run))
    if user is not None and record is None:
        # Not in this process's memory: it may have run before a restart.
        try:
            stored = history.fetch(user, task_id)
        except history.HistoryUnavailable:
            stored = None
        if stored is not None:
            return TaskResponse.model_validate(stored)
    # Someone else's task is reported exactly like a missing one.
    raise HTTPException(404, f"No task with id '{task_id}'.")


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

    media_type = ARTIFACT_MEDIA_TYPES.get(
        os.path.splitext(path)[1].lower(), "application/octet-stream"
    )
    return FileResponse(path, media_type=media_type, filename=os.path.basename(path))


# ============================================================
# FRONTEND-FACING ALIASES
# ============================================================
# The same handlers, mounted at the names the frontend contract specifies.
# They are aliases rather than reimplementations so the two can never drift:
# there is exactly one code path per operation.
analysis_router = APIRouter(tags=["analysis"])

analysis_router.add_api_route(
    "/analyze", create_task, methods=["POST"], response_model=TaskResponse,
    summary="Run a natural-language analysis over uploaded imagery",
)
analysis_router.add_api_route(
    "/analyze/validate", validate_task, methods=["POST"],
    response_model=ValidationResponse,
    summary="Check whether a request would run, without executing it",
)
analysis_router.add_api_route(
    "/results/{task_id}", get_task, methods=["GET"], response_model=TaskResponse,
    summary="Retrieve a completed result",
)
analysis_router.add_api_route(
    "/results/{task_id}/artifacts/{artifact_id}", download_artifact, methods=["GET"],
    summary="Download a raster produced by a result",
)
