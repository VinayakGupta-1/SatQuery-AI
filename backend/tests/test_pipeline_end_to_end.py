"""End-to-end tests running a natural-language query through every stage.

Each controller layer already has its own unit tests, but nothing verified that
the layers actually compose: that what one stage emits is what the next stage
can consume. These tests run the real :class:`SatQueryPipeline` over a real
GeoTIFF --

    query -> understanding -> classification -> planning -> requirements
          -> validation -> tool selection -> parameters -> execution
          -> result integration

-- and assert on the NDVI values that come out the far end.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.controller.pipeline import SatQueryPipeline
from app.schemas.inputs import ImageInput, ImageMetadata
from app.tools.raster.io import open_raster
from tests.conftest import SENTINEL2_EXPECTED_NDVI


@pytest.fixture
def pipeline():
    return SatQueryPipeline()


@pytest.fixture
def outputs(tmp_path):
    return str(tmp_path / "outputs")


def optical_image(path, bands=("red", "nir")):
    return ImageInput(
        id="scene_1",
        path=path,
        metadata=ImageMetadata(
            acquisition_date=date(2026, 3, 1),
            modality="optical",
            sensor="sentinel2",
            crs="EPSG:32643",
            width=2,
            height=2,
            bands=list(bands),
        ),
    )


# ============================================================
# THE HAPPY PATH
# ============================================================
def test_ndvi_query_runs_through_every_stage(pipeline, sentinel2_scene, outputs):
    run = pipeline.run(
        "Calculate vegetation health from this satellite image",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
    )

    assert run.understanding.task_type == "ndvi"
    assert run.classification.task_category == "index_analysis"
    assert run.requirements.required_bands == ["red", "nir"]
    assert run.validation.valid
    assert run.selection.selected_tool_id == "ndvi"
    assert run.configuration.status == "configured"
    assert run.execution.status == "completed"
    assert run.succeeded
    assert run.execution.output["statistics"]["mean"] == pytest.approx(0.2)


def test_stage_status_summarises_the_run(pipeline, sentinel2_scene, outputs):
    run = pipeline.run(
        "Calculate NDVI for this satellite image",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
    )

    assert run.stage_status() == {
        "understanding": "ndvi",
        "classification": "index_analysis",
        "planning": "planned",
        "validation": "valid",
        "tool_selection": "selected",
        "parameter_configuration": "configured",
        "execution": "completed",
    }


def test_pipeline_produces_a_real_ndvi_raster(pipeline, sentinel2_scene, outputs):
    run = pipeline.run(
        "Calculate NDVI for this satellite image",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
    )

    artifacts = run.execution.execution_metadata["artifacts"]
    assert len(artifacts) == 1

    result = open_raster(artifacts[0])
    assert result.band_at(1).to_list() == pytest.approx(SENTINEL2_EXPECTED_NDVI, abs=1e-6)
    assert result.georeference.crs == "EPSG:32643"


def test_configurator_band_names_survive_into_execution(
    pipeline, sentinel2_scene, outputs
):
    # The configurator resolves the logical names "red" and "nir" from the
    # requirements; the tool layer must map those onto B4 and B8.
    run = pipeline.run(
        "Calculate NDVI for this satellite image",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
    )

    assert run.configuration.resolved_parameters["red_band"] == "red"
    assert run.configuration.resolved_parameters["nir_band"] == "nir"
    assert run.execution.output["data"]["formula"] == "(B8 - B4) / (B8 + B4)"


def test_explicit_user_bands_reach_the_tool(pipeline, sentinel2_scene, outputs):
    run = pipeline.run(
        "Calculate NDVI for this satellite image",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
        user_parameters={"red_band": "B4", "nir_band": "B8"},
    )

    assert run.execution.status == "completed"
    assert run.execution.output["data"]["negative_band"] == "B4"


def test_pipeline_answers_the_question_in_plain_language(
    pipeline, sentinel2_scene, outputs
):
    run = pipeline.run(
        "Calculate vegetation health from this satellite image",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
    )

    final = run.final
    assert final.task_id == run.task_id
    assert "Mean NDVI is 0.200" in final.answer
    assert final.results[0].result_type == "raster_index"
    assert final.execution_summary.tools_used == ["ndvi"]
    assert final.results[0].data["artifacts"][0].endswith("_ndvi.tif")


def test_each_run_gets_its_own_task_id(pipeline, sentinel2_scene, outputs):
    images = [optical_image(sentinel2_scene)]
    first = pipeline.run("Calculate NDVI", images, output_directory=outputs)
    second = pipeline.run("Calculate NDVI", images, output_directory=outputs)

    assert first.task_id != second.task_id
    assert first.task_id.startswith("task_")


def test_an_explicit_task_id_is_kept(pipeline, sentinel2_scene, outputs):
    run = pipeline.run(
        "Calculate NDVI",
        [optical_image(sentinel2_scene)],
        task_id="sih_demo_1",
        output_directory=outputs,
    )

    assert run.task_id == "sih_demo_1"
    assert run.final.task_id == "sih_demo_1"


def test_ndwi_query_selects_and_runs_the_water_index(pipeline, raster_factory, outputs):
    from tests.conftest import make_band

    path = raster_factory(
        "water.tif",
        [make_band("B3", [3000, 1000], 2, 1), make_band("B8", [1000, 3000], 2, 1)],
    )
    image = optical_image(path, bands=["green", "nir"])

    run = pipeline.run(
        "Find water bodies in this satellite image", [image], output_directory=outputs
    )

    assert run.understanding.task_type == "ndwi"
    assert run.selection.selected_tool_id == "ndwi"
    assert run.execution.status == "completed"
    assert run.execution.output["data"]["formula"] == "(B3 - B8) / (B3 + B8)"


def test_ndbi_query_selects_and_runs_the_builtup_index(
    pipeline, raster_factory, outputs
):
    # NDBI was previously unreachable: no query could produce it, so the tool
    # existed but nothing could ask for it.
    from tests.conftest import make_band

    path = raster_factory(
        "urban.tif",
        [make_band("B8", [1000, 3000], 2, 1), make_band("B11", [3000, 1000], 2, 1)],
    )
    image = optical_image(path, bands=["nir", "swir1"])

    run = pipeline.run(
        "Map the built-up area in this satellite image",
        [image],
        output_directory=outputs,
    )

    assert run.understanding.task_type == "ndbi"
    assert run.classification.task_category == "index_analysis"
    assert run.requirements.required_bands == ["nir", "swir"]
    assert run.selection.selected_tool_id == "ndbi"
    assert run.execution.status == "completed"
    # NDBI puts SWIR in the positive role.
    assert run.execution.output["data"]["formula"] == "(B11 - B8) / (B11 + B8)"
    assert run.execution.output["statistics"]["mean"] == pytest.approx(0.0)


def test_building_detection_still_routes_to_object_detection(
    pipeline, sentinel2_scene, outputs
):
    # The new built-up keywords must not swallow discrete-object queries.
    run = pipeline.run(
        "Detect buildings in this satellite image",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
    )

    assert run.understanding.task_type == "object_detection"
    assert run.selection.selected_tool_id == "object_detection"


# ============================================================
# THE VALIDATOR STOPS BAD INPUT BEFORE EXECUTION
# ============================================================
def test_sar_input_is_rejected_for_an_optical_index(pipeline, sentinel2_scene, outputs):
    sar = ImageInput(
        id="scene_1",
        path=sentinel2_scene,
        metadata=ImageMetadata(
            acquisition_date=date(2026, 3, 1),
            modality="sar",
            sensor="sentinel1",
            crs="EPSG:32643",
            bands=["vv", "vh"],
        ),
    )

    run = pipeline.run(
        "Calculate NDVI for this satellite image", [sar], output_directory=outputs
    )

    assert not run.validation.valid
    assert run.execution is None
    assert run.configuration is None

    codes = {issue.code.value for issue in run.validation.errors}
    assert "MODALITY_MISMATCH" in codes

    # The rejection still returns the same contract the frontend renders.
    assert "rejected before execution" in run.final.answer
    assert run.final.results == []


def test_missing_required_band_is_rejected(pipeline, sentinel2_scene, outputs):
    image = optical_image(sentinel2_scene, bands=["red", "green"])  # no NIR

    run = pipeline.run(
        "Calculate NDVI for this satellite image", [image], output_directory=outputs
    )

    assert not run.validation.valid
    assert run.execution is None
    assert any("nir" in issue.message for issue in run.validation.errors)


def test_missing_crs_is_rejected(pipeline, sentinel2_scene, outputs):
    image = ImageInput(
        id="scene_1",
        path=sentinel2_scene,
        metadata=ImageMetadata(modality="optical", bands=["red", "nir"]),
    )

    run = pipeline.run(
        "Calculate NDVI for this satellite image", [image], output_directory=outputs
    )

    assert not run.validation.valid
    codes = {issue.code.value for issue in run.validation.errors}
    assert "CRS_MISMATCH" in codes


def test_second_image_is_rejected_for_a_single_image_tool(
    pipeline, sentinel2_scene, outputs
):
    images = [optical_image(sentinel2_scene), optical_image(sentinel2_scene)]

    run = pipeline.run(
        "Calculate NDVI for this satellite image", images, output_directory=outputs
    )

    assert not run.validation.valid
    codes = {issue.code.value for issue in run.validation.errors}
    assert "INVALID_IMAGE_COUNT" in codes


# ============================================================
# CHANGE DETECTION
# ============================================================
def dated_image(path, image_id, acquisition):
    return ImageInput(
        id=image_id,
        path=path,
        metadata=ImageMetadata(
            acquisition_date=acquisition,
            modality="optical",
            crs="EPSG:32643",
            bands=["red", "nir"],
        ),
    )


def test_change_detection_runs_through_the_whole_pipeline(
    pipeline, sentinel2_scene, outputs
):
    # The same scene compared against itself: a real run whose correct answer
    # is that nothing changed.
    images = [
        dated_image(sentinel2_scene, "before", date(2024, 1, 1)),
        dated_image(sentinel2_scene, "after", date(2026, 1, 1)),
    ]

    run = pipeline.run(
        "Compare these two satellite images and identify changes",
        images,
        output_directory=outputs,
    )

    assert run.classification.task_category == "change_detection"
    assert run.validation.valid
    assert run.selection.selected_tool_id == "change_detection"
    assert run.execution.status == "completed"

    assert run.execution.output["statistics"]["changed_pixels"] == 0
    assert run.final.execution_summary.tools_used == ["change_detection"]
    assert "0 of 4 comparable pixels changed" in run.final.answer

    # A difference raster and a classification raster.
    assert len(run.execution.execution_metadata["artifacts"]) == 2


def test_change_detection_finds_real_change(pipeline, raster_factory, outputs):
    from tests.conftest import make_band

    def forest(name, red, nir):
        return raster_factory(
            name, [make_band("B4", red, 2, 1), make_band("B8", nir, 2, 1)]
        )

    # Pixel 0 is cleared between the dates; pixel 1 is untouched.
    earlier = forest("t1.tif", red=[1000, 1000], nir=[4000, 3000])
    later = forest("t2.tif", red=[3000, 1000], nir=[1000, 3000])

    run = pipeline.run(
        "Detect changes between these two satellite images",
        [
            dated_image(earlier, "before", date(2024, 6, 1)),
            dated_image(later, "after", date(2026, 6, 1)),
        ],
        output_directory=outputs,
    )

    assert run.execution.status == "completed"
    statistics = run.execution.output["statistics"]
    assert statistics["changed_pixels"] == 1
    assert statistics["valid_pixels"] == 2

    classes = run.execution.output["data"]["classes"]
    assert classes["decrease"]["pixels"] == 1
    assert classes["stable"]["pixels"] == 1

    assert "vegetation loss" in run.final.answer


# ============================================================
# UNIMPLEMENTED CAPABILITIES STILL REPORT HONESTLY
# ============================================================
def test_an_unbuilt_capability_is_reported_not_faked(
    pipeline, sentinel2_scene, outputs
):
    run = pipeline.run(
        "What is in this image?",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
    )

    assert run.selection.selected_tool_id == "satellite_vqa"
    assert run.execution.status == "blocked"
    assert "no execution implementation" in run.execution.error
    assert "blocked before the tool ran" in run.final.answer
    assert run.final.results == []


def test_temporal_pair_with_identical_dates_is_rejected(
    pipeline, sentinel2_scene, outputs
):
    same_date = date(2026, 1, 1)
    images = [
        dated_image(sentinel2_scene, "before", same_date),
        dated_image(sentinel2_scene, "after", same_date),
    ]

    run = pipeline.run(
        "Compare these two satellite images and identify changes",
        images,
        output_directory=outputs,
    )

    assert not run.validation.valid
    codes = {issue.code.value for issue in run.validation.errors}
    assert "TEMPORAL_INCOMPATIBILITY" in codes


def test_an_unrecognised_query_asks_for_clarification(
    pipeline, sentinel2_scene, outputs
):
    run = pipeline.run(
        "make it look nicer please",
        [optical_image(sentinel2_scene)],
        output_directory=outputs,
    )

    assert run.selection.status == "requires_clarification"
    assert run.execution is None
    assert "did not reach execution" in run.final.answer
    assert run.stage_status()["execution"] == "not_reached"


# ============================================================
# THE BRIDGE ITSELF
# ============================================================
def test_bridge_drops_descriptive_placeholders():
    from app.controller.input_requirements.input_requirements import InputRequirements
    from app.controller.input_requirements.validation_bridge import (
        to_validation_requirements,
    )

    requirements = InputRequirements(
        task_category="image_analysis",
        minimum_image_count=1,
        required_modalities=["compatible_imagery"],
        required_bands=["required_spectral_bands"],
        requires_metadata=True,
        requires_crs=True,
    )

    translated = to_validation_requirements(requirements)

    # "compatible_imagery" is not a modality to match against metadata.
    assert translated.required_modalities == []
    assert translated.required_bands == []
    assert not translated.requires_optical_input
    assert translated.requires_metadata
    assert translated.min_images == 1


def test_bridge_takes_the_image_ceiling_from_the_registry():
    from app.controller.input_requirements.input_requirements import InputRequirements
    from app.controller.input_requirements.validation_bridge import (
        to_validation_requirements,
    )
    from app.registry.registry import get_tool

    requirements = InputRequirements(
        task_category="index_analysis",
        minimum_image_count=1,
        required_modalities=["optical"],
        required_bands=["red", "nir"],
    )

    without_tool = to_validation_requirements(requirements)
    with_tool = to_validation_requirements(requirements, get_tool("ndvi"))

    assert without_tool.max_images == 0  # unbounded
    assert with_tool.max_images == 1
    assert with_tool.requires_optical_input


def test_bridge_rejects_the_wrong_requirements_model():
    from app.controller.input_requirements.validation_bridge import (
        to_validation_requirements,
    )

    with pytest.raises(TypeError):
        to_validation_requirements({"minimum_image_count": 1})
