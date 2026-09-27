"""The four capabilities that used to be unbound, driven through the pipeline.

Each test starts from a sentence and real rasters and checks the whole route:
which task the sentence was read as, what the imagery changed about that, which
tool was selected, what the validator enforced, and what came back.
"""

from __future__ import annotations

import pytest

from app.agents.agent import QueryAgent, to_task_understanding
from app.agents.providers import RuleBasedProvider
from app.agents.schemas import AgentTaskPlan
from app.controller.input_requirements.input_requirements import change_index_for
from app.controller.pipeline import SatQueryPipeline
from app.controller.task_understanding import TaskUnderstanding, adapt_to_imagery
from app.schemas.inputs import ImageInput
from app.tools.raster.inspection import describe_raster
from app.tools.raster.io import open_raster
from tests.conftest import make_band


@pytest.fixture
def pipeline():
    return SatQueryPipeline(agent=QueryAgent(provider=RuleBasedProvider()))


def image(path, image_id="image_1"):
    return ImageInput(id=image_id, path=path, metadata=describe_raster(path))


@pytest.fixture
def optical(raster_factory):
    """A 5-band 4x4 scene: a water column, a built-up column, dense vegetation."""
    green, red, nir, swir = [], [], [], []
    for _row in range(4):
        for col in range(4):
            if col == 0:
                values = (1000, 600, 200, 100)  # water
            elif col == 1:
                values = (1400, 1600, 1900, 2400)  # built-up
            else:
                values = (800, 500, 4000, 1500)  # dense vegetation
            for target, value in zip((green, red, nir, swir), values):
                target.append(value)
    bands = [
        make_band("B2", [700] * 16, 4, 4),
        make_band("B3", green, 4, 4),
        make_band("B4", red, 4, 4),
        make_band("B8", nir, 4, 4),
        make_band("B11", swir, 4, 4),
    ]
    return raster_factory("optical.tif", bands, metadata_extra={"acquisition_date": "2024-01-10"})


def sar_scene(raster_factory, name, water_columns, date):
    """A 12x12 VV scene in dB: water (-22 dB) in the given columns, land -9 dB."""
    values = [
        -22.0 if col in water_columns else -9.0 for _row in range(12) for col in range(12)
    ]
    return raster_factory(
        name,
        [make_band("VV", values, 12, 12, dtype="float32")],
        sensor="sentinel1",
        metadata_extra={"acquisition_date": date},
    )


# ============================================================
# READING THE SENTENCE
# ============================================================
@pytest.mark.parametrize(
    "query, expected",
    [
        ("How many water bodies are there?", "object_detection"),
        ("Count the lakes in this scene", "object_detection"),
        ("How many hectares of vegetation are there?", "ndvi"),
        ("Find areas affected by flooding", "flood_mapping"),
        ("Map the water in this SAR image", "sar_analysis"),
        ("Show the radar backscatter", "sar_analysis"),
        ("Is it necessary to map the vegetation?", "ndvi"),
        ("Classify the land cover into vegetation and water", "segmentation"),
        ("Show vegetation health", "ndvi"),
        ("Compare these two radar images and show where flooding appeared", "change_detection"),
    ],
)
def test_sentences_route_to_the_right_task(query, expected):
    assert TaskUnderstanding().understand(query).task_type == expected


def test_water_mapping_follows_the_sensor():
    understood = TaskUnderstanding().understand("Find areas affected by flooding")

    on_radar, note = adapt_to_imagery(understood, {"sar"})
    assert on_radar.task_type == "sar_analysis"
    assert on_radar.imagery_modality == "sar"
    assert "backscatter" in note

    on_optical, note = adapt_to_imagery(understood, {"optical"})
    assert on_optical.task_type == "ndwi"
    assert "NDWI" in note


def test_a_non_water_task_is_left_for_the_validator_to_judge():
    understood = TaskUnderstanding().understand("How healthy is the vegetation?")
    adapted, note = adapt_to_imagery(understood, {"sar"})
    assert adapted.task_type == "ndvi"
    assert note is None


@pytest.mark.parametrize(
    "query, index",
    [
        ("Compare these images and show how the water changed", "ndwi"),
        ("Where has new construction appeared between these dates?", "ndbi"),
        ("Identify vegetation change between 2023 and 2025", "ndvi"),
        ("Find change between these images", "ndvi"),
    ],
)
def test_change_detection_differences_the_index_the_question_is_about(query, index):
    assert change_index_for(TaskUnderstanding().understand(query)) == index


def test_a_hosted_models_unfamiliar_task_label_is_recovered_from_its_tool():
    plan = AgentTaskPlan(task="vegetation_health_assessment", tool="ndvi", provider="hosted")
    assert to_task_understanding(plan, "q").task_type == "ndvi"


# ============================================================
# THE WHOLE ROUTE
# ============================================================
def test_land_cover_is_classified(pipeline, optical, tmp_path):
    run = pipeline.run(
        "Classify the land cover in this image", [image(optical)], output_directory=str(tmp_path)
    )

    assert run.selection.selected_tool_id == "land_cover_classification"
    assert run.status == "success"
    classes = run.execution.output["data"]["classes"]
    assert classes["water"]["pixels"] == 4
    assert classes["built_up"]["pixels"] == 4
    assert classes["dense_vegetation"]["pixels"] == 8
    assert "dense vegetation" in run.final.answer


def test_segmentation_is_served_by_the_land_cover_classifier(pipeline, optical, tmp_path):
    run = pipeline.run(
        "Segment this image", [image(optical)], output_directory=str(tmp_path)
    )
    assert run.selection.selected_tool_id == "land_cover_classification"
    assert run.status == "success"


def test_water_bodies_are_counted(pipeline, optical, tmp_path):
    # The fixture's lake is 4 pixels: below the default 9-pixel minimum, so it
    # is dropped and reported as dropped rather than silently counted.
    run = pipeline.run(
        "How many water bodies are there?", [image(optical)], output_directory=str(tmp_path)
    )
    assert run.selection.selected_tool_id == "object_detection"
    assert run.status == "success"
    assert run.execution.output["data"]["counts"] == {"water_body": 0}
    assert run.execution.output["statistics"]["regions_below_minimum"] == 1

    run = pipeline.run(
        "How many water bodies are there?",
        [image(optical)],
        output_directory=str(tmp_path),
        user_parameters={"min_area_pixels": 1},
    )
    assert run.execution.output["data"]["counts"] == {"water_body": 1}
    assert "Found 1 discrete object: 1 water body" in run.final.answer


def test_asking_for_buildings_explains_why_not_instead_of_failing(pipeline, optical, tmp_path):
    run = pipeline.run(
        "Detect buildings in this satellite image", [image(optical)], output_directory=str(tmp_path)
    )

    assert run.execution.status == "blocked"
    assert run.status == "needs_clarification"
    assert "sub-metre imagery" in run.clarification


def test_land_cover_on_radar_is_rejected_by_the_validator(pipeline, raster_factory, tmp_path):
    radar = sar_scene(raster_factory, "radar.tif", {0}, "2024-06-10")
    run = pipeline.run(
        "Classify the land cover", [image(radar)], output_directory=str(tmp_path)
    )
    assert run.status == "validation_error"
    assert run.execution is None


def test_flooding_on_radar_is_mapped_from_backscatter(pipeline, raster_factory, tmp_path):
    radar = sar_scene(raster_factory, "flood.tif", set(range(6)), "2024-08-22")
    run = pipeline.run(
        "Find areas affected by flooding", [image(radar)], output_directory=str(tmp_path)
    )

    assert run.understanding.task_type == "sar_analysis"
    assert run.selection.selected_tool_id == "sar_analysis"
    assert run.status == "success"
    water = run.execution.output["data"]["classes"]["water"]["fraction"]
    assert water == pytest.approx(0.5, abs=0.1)
    assert any("backscatter" in note for note in run.agent.notes)


def test_flooding_on_optical_imagery_is_mapped_with_ndwi(pipeline, optical, tmp_path):
    run = pipeline.run(
        "Find areas affected by flooding", [image(optical)], output_directory=str(tmp_path)
    )
    assert run.selection.selected_tool_id == "ndwi"
    assert run.status == "success"


def test_two_radar_dates_are_compared_by_log_ratio(pipeline, raster_factory, tmp_path):
    before = sar_scene(raster_factory, "before.tif", set(), "2024-06-10")
    after = sar_scene(raster_factory, "after.tif", set(range(6)), "2024-08-22")

    run = pipeline.run(
        "Compare these two radar images and show where flooding appeared",
        [image(before, "image_1"), image(after, "image_2")],
        output_directory=str(tmp_path),
    )

    assert run.selection.selected_tool_id == "change_detection"
    assert run.status == "success"
    data = run.execution.output["data"]
    assert data["method"] == "sar_log_ratio"
    assert data["classes"]["increase"]["pixels"] == 0
    assert data["classes"]["decrease"]["fraction"] == pytest.approx(0.5, abs=0.15)
    assert "backscatter loss, typical of new open water" in run.final.answer


def test_a_water_change_question_on_optical_imagery_uses_ndwi(pipeline, raster_factory, optical, tmp_path):
    later = raster_factory(
        "optical_later.tif",
        open_raster(optical).bands,
        metadata_extra={"acquisition_date": "2024-09-10"},
    )
    run = pipeline.run(
        "Compare these images and show how the water changed",
        [image(optical, "image_1"), image(later, "image_2")],
        output_directory=str(tmp_path),
    )
    assert run.configuration.resolved_parameters["index"] == "ndwi"
    assert run.execution.output["data"]["index"] == "NDWI"


# ============================================================
# THE DRY RUN
# ============================================================
def test_a_dry_run_authorises_without_computing(pipeline, optical, tmp_path):
    outputs = tmp_path / "dry"
    run = pipeline.run(
        "Classify the land cover", [image(optical)], output_directory=str(outputs), execute=False
    )

    assert run.outcome == "authorised"
    assert run.would_execute is True
    assert run.execution.output is None
    assert run.stage_status()["execution"] == "authorised"
    assert not outputs.exists() or not any(outputs.iterdir())


def test_a_dry_run_reports_a_refusal_it_can_see_in_advance(pipeline, optical, tmp_path):
    run = pipeline.run(
        "Detect buildings", [image(optical)], output_directory=str(tmp_path), execute=False
    )
    assert run.would_execute is False
    assert "sub-metre imagery" in run.refusal


def test_a_question_says_when_vqa_is_switched_off():
    plan = RuleBasedProvider().understand("Is there a river in this image?")
    assert plan.task is None
    assert "switched off" in plan.clarification
