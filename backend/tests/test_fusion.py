"""Tests for optical + SAR water fusion.

The scene is six pixels, one for every case the fusion distinguishes, so each
label and the agreement statistic can be checked by hand::

    pixel  optical (SCL, NDWI)      radar (VV dB)   fused
      0    clear, water  +0.67      -22  water      water, both sensors
      1    clear, land   -0.67      -22  water      water, radar only
      2    clear, water  +0.67       -9  land       water, optical only
      3    cloud                     -22  water      water under cloud
      4    clear, land   -0.67       -9  land       land
      5    cloud                      -9  land       land

Pixels both sensors observed: 0, 1, 2, 4. They agree on two of the four
(0 and 4), and each sensor says "water" on half of them, so the agreement
expected by chance is also one half: Cohen's kappa is exactly zero.
"""

from __future__ import annotations

import array
import math

import pytest

from app.agents.agent import QueryAgent
from app.agents.providers import RuleBasedProvider
from app.controller.pipeline import SatQueryPipeline
from app.schemas.inputs import ImageInput
from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.fusion import tool as fusion_module
from app.tools.fusion.tool import CLASS_LABELS, OpticalSARFusionTool, fuse
from app.tools.raster.inspection import describe_raster
from app.tools.raster.model import BandArray
from tests.conftest import make_band

WATER, LAND = (1000, 200), (800, 4000)  # (green, nir): NDWI +0.67 and -0.67
CLEAR, CLOUD = 4, 9  # SCL: vegetation, cloud high probability


def optical_scene(raster_factory, date="2024-08-22", name="optical.tif"):
    pixels = [(WATER, CLEAR), (LAND, CLEAR), (WATER, CLEAR), (WATER, CLOUD), (LAND, CLEAR), (LAND, CLOUD)]
    green = [p[0][0] for p in pixels]
    nir = [p[0][1] for p in pixels]
    scl = [p[1] for p in pixels]
    return raster_factory(
        name,
        [make_band("B3", green, 3, 2), make_band("B8", nir, 3, 2), make_band("SCL", scl, 3, 2)],
        metadata_extra={"acquisition_date": date},
    )


def radar_scene(raster_factory, date="2024-08-22", name="radar.tif"):
    return raster_factory(
        name,
        [make_band("VV", [-22.0, -22.0, -9.0, -22.0, -9.0, -9.0], 3, 2, dtype="float32")],
        sensor="sentinel1",
        metadata_extra={"acquisition_date": date},
    )


def run_fusion(paths, tmp_path, **parameters):
    return OpticalSARFusionTool().execute(
        ToolRequest(
            tool_id="optical_sar_fusion",
            input_references=paths,
            parameters={"speckle_filter": "none", **parameters},
            output_directory=str(tmp_path / "out"),
        )
    )


# ============================================================
# THE PIXEL RULE
# ============================================================
def _fuse_inputs():
    nan = float("nan")
    ndwi = BandArray(
        name="ndwi", width=3, height=2,
        values=array.array("d", [0.67, -0.67, 0.67, nan, -0.67, nan]), dtype="float64",
    )
    decibels = [-22.0, -22.0, -9.0, -22.0, -9.0, -9.0]
    return ndwi, decibels, [True] * 6


@pytest.mark.parametrize("numpy_available", [True, False])
def test_every_pixel_is_labelled_by_what_each_sensor_saw(monkeypatch, numpy_available):
    if numpy_available:
        pytest.importorskip("numpy")
    monkeypatch.setattr(fusion_module, "has_numpy", lambda: numpy_available)
    ndwi, decibels, valid = _fuse_inputs()

    codes, counts, agreement = fuse(ndwi, 0.0, decibels, valid, -18.0)

    assert [CLASS_LABELS[int(code)] for code in codes] == [
        "water_both", "water_radar_only", "water_optical_only", "water_under_cloud", "land", "land",
    ]
    assert counts["land"] == 2 and counts["water_under_cloud"] == 1
    assert agreement["pixels_seen_by_both"] == 4
    assert agreement["observed_agreement"] == pytest.approx(0.5)
    assert agreement["kappa"] == pytest.approx(0.0)


def test_perfect_agreement_scores_a_kappa_of_one():
    ndwi = BandArray(name="ndwi", width=2, height=1, values=array.array("d", [0.5, -0.5]), dtype="float64")
    _, _, agreement = fuse(ndwi, 0.0, [-22.0, -9.0], [True, True], -18.0)
    assert agreement["kappa"] == pytest.approx(1.0)


def test_a_pixel_neither_sensor_saw_is_left_as_nodata():
    ndwi = BandArray(name="ndwi", width=1, height=1, values=array.array("d", [math.nan]), dtype="float64")
    codes, counts, agreement = fuse(ndwi, 0.0, [-22.0], [False], -18.0)
    assert int(codes[0]) == 0
    assert sum(counts.values()) == 0
    assert "kappa" not in agreement


# ============================================================
# THE TOOL
# ============================================================
def test_the_pair_is_fused_with_cloud_masked_automatically(raster_factory, tmp_path):
    output = run_fusion([optical_scene(raster_factory), radar_scene(raster_factory)], tmp_path)

    classes = output.data["classes"]
    assert {label: entry["pixels"] for label, entry in classes.items()} == {
        "water_both": 1, "water_radar_only": 1, "water_optical_only": 1,
        "water_under_cloud": 1, "land": 2,
    }
    assert output.data["cloud_mask"] == "SCL"
    assert output.data["days_apart"] == 0
    assert output.statistics["water_pixels"] == 4
    assert output.statistics["kappa"] == pytest.approx(0.0)
    assert output.statistics["optical_masked_fraction"] == pytest.approx(2 / 6)
    assert {artifact.artifact_id for artifact in output.artifacts} == {
        "fusion_raster", "scene_preview", "radar_preview",
    }


def test_the_order_of_the_two_images_does_not_matter(raster_factory, tmp_path):
    optical, radar = optical_scene(raster_factory), radar_scene(raster_factory)
    forward = run_fusion([optical, radar], tmp_path, write_raster=False)
    reverse = run_fusion([radar, optical], tmp_path, write_raster=False)
    assert forward.data["classes"] == reverse.data["classes"]


def test_two_optical_images_are_refused(raster_factory, tmp_path):
    first = optical_scene(raster_factory)
    second = optical_scene(raster_factory, name="optical_2.tif")
    with pytest.raises(ToolExecutionError, match="both optical"):
        run_fusion([first, second], tmp_path)


def test_images_weeks_apart_are_refused(raster_factory, tmp_path):
    optical = optical_scene(raster_factory, date="2024-08-01")
    radar = radar_scene(raster_factory, date="2024-08-30")
    with pytest.raises(ToolExecutionError, match="29 days apart"):
        run_fusion([optical, radar], tmp_path)
    # The operator can widen the window deliberately.
    assert run_fusion([optical, radar], tmp_path, max_days_apart=30, write_raster=False).data["days_apart"] == 29


def test_a_negative_day_window_is_refused_before_any_work():
    with pytest.raises(ToolExecutionError, match="cannot be negative"):
        OpticalSARFusionTool().preflight(
            ToolRequest(tool_id="optical_sar_fusion", parameters={"max_days_apart": -1})
        )


# ============================================================
# THROUGH THE PIPELINE
# ============================================================
def _image(path, image_id):
    return ImageInput(id=image_id, path=path, metadata=describe_raster(path))


@pytest.mark.parametrize(
    "query",
    ["Find areas affected by flooding", "Fuse the optical and radar images to map water"],
)
def test_an_optical_and_a_sar_image_are_fused(raster_factory, tmp_path, query):
    pipeline = SatQueryPipeline(agent=QueryAgent(provider=RuleBasedProvider()))
    run = pipeline.run(
        query,
        [_image(optical_scene(raster_factory), "image_1"), _image(radar_scene(raster_factory), "image_2")],
        output_directory=str(tmp_path),
        user_parameters={"speckle_filter": "none"},
    )

    assert run.selection.selected_tool_id == "optical_sar_fusion"
    assert run.status == "success"
    assert run.execution.output["data"]["classes"]["water_under_cloud"]["pixels"] == 1
    report = run.final.confidence_report
    assert {factor.name for factor in report.factors} >= {"coverage", "agreement"}
    # Kappa of zero is the weakest link, and the report says so.
    assert report.score == pytest.approx(0.0)
    assert "agreement" in report.basis
