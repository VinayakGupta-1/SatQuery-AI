"""Flooding as new water: a flood-period scene against a dry-season reference.

The scenes are 4 x 1 strips of VV backscatter in dB, chosen so each column is
one flood class (water is below -18 dB)::

    column             0        1         2          3
    reference (Apr)   -25 W    -10 dry   -25 W      -10 dry
    event (Aug)       -25 W    -25 W     -10 dry    -10 dry
                      permanent flooded  receded    dry land
"""

from __future__ import annotations

from datetime import date

import pytest

from app.acquisition.planner import dry_season_before, plan_acquisition
from app.config.settings import Settings
from app.controller.pipeline import SatQueryPipeline
from app.controller.task_understanding.task_understanding import TaskUnderstanding
from app.schemas.inputs import ImageInput
from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.raster.inspection import describe_raster
from app.tools.sar.tool import SARAnalysisTool
from tests.conftest import make_band

REFERENCE = [-25.0, -10.0, -25.0, -10.0]
EVENT = [-25.0, -25.0, -10.0, -10.0]


@pytest.fixture
def pair(raster_factory):
    def scene(name, values, day):
        return raster_factory(
            name,
            [make_band("VV", values, 4, 1, dtype="float32")],
            sensor="sentinel1",
            metadata_extra={"ACQUISITION_DATE": day, "modality": "sar"},
        )

    return scene("reference.tif", REFERENCE, "2024-04-27"), scene("event.tif", EVENT, "2024-08-25")


def run(paths, tmp_path, **parameters):
    return SARAnalysisTool().execute(
        ToolRequest(
            tool_id="sar_analysis",
            input_references=list(paths),
            parameters={"speckle_filter": "none", **parameters},
            output_directory=str(tmp_path / "out"),
        )
    )


def test_each_pixel_is_flooded_permanent_receded_or_dry(pair, tmp_path):
    output = run(pair, tmp_path)
    classes = output.data["classes"]
    assert {name: entry["pixels"] for name, entry in classes.items()} == {
        "flooded": 1, "permanent_water": 1, "receded_water": 1, "dry_land": 1,
    }
    assert output.result_type == "sar_flood_map"
    assert output.statistics["flooded_fraction"] == pytest.approx(0.25)
    assert (output.data["reference_date"], output.data["event_date"]) == ("2024-04-27", "2024-08-25")


def test_the_order_of_the_files_does_not_matter(pair, tmp_path):
    reference, event = pair
    swapped = run([event, reference], tmp_path)
    assert swapped.data["classes"]["flooded"]["pixels"] == 1
    assert swapped.data["reference_date"] == "2024-04-27"


def test_one_threshold_is_used_for_both_dates(pair, tmp_path):
    # At -30 dB nothing is water on either date, so nothing can be "new".
    output = run(pair, tmp_path, threshold_db=-30)
    assert output.data["classes"]["flooded"]["pixels"] == 0
    assert output.data["classes"]["dry_land"]["pixels"] == 4


def test_a_pair_without_dates_is_refused(raster_factory, tmp_path):
    undated = [
        raster_factory(f"{name}.tif", [make_band("VV", values, 4, 1, dtype="float32")], sensor="sentinel1")
        for name, values in (("a", REFERENCE), ("b", EVENT))
    ]
    with pytest.raises(ToolExecutionError, match="acquisition dates"):
        run(undated, tmp_path)


def test_the_answer_separates_flood_from_permanent_water(pair, tmp_path):
    images = [
        ImageInput(id=f"image_{index}", path=path, metadata=describe_raster(path))
        for index, path in enumerate(pair, start=1)
    ]
    run_ = SatQueryPipeline().run(
        "Find the areas affected by flooding in August 2024", images,
        output_directory=str(tmp_path / "out"),
        user_parameters={"speckle_filter": "none"},
    )
    # The April reference predates "August 2024" on purpose and is accepted.
    assert run_.status == "success", run_.final.answer
    answer = run_.final.answer
    assert answer.startswith("Flooding covers 25.0% of the observed area")
    assert "not counted as flood" in answer


def test_a_single_scene_is_still_a_water_map(pair, tmp_path):
    output = run(pair[1:], tmp_path)
    assert output.result_type == "sar_water_map"


# ============================================================
# FETCHING THE PAIR
# ============================================================
@pytest.mark.parametrize(
    "start, reference",
    [
        (date(2024, 8, 1), (date(2024, 1, 1), date(2024, 4, 30))),
        (date(2024, 3, 1), (date(2023, 1, 1), date(2023, 4, 30))),
    ],
)
def test_the_reference_is_the_preceding_dry_season(start, reference):
    assert dry_season_before(start) == reference


def test_a_flood_question_plans_a_reference_and_an_event_scene():
    understanding = TaskUnderstanding().understand("Find the flooding near Kochi in August 2024")
    plan = plan_acquisition(understanding, Settings(), date(2026, 10, 17))
    reference, event = plan.requests
    assert plan.kind == "flood"
    assert (reference.role, reference.start, reference.end) == ("reference", date(2024, 1, 1), date(2024, 4, 30))
    assert (event.role, event.start, event.end) == ("event", date(2024, 8, 1), date(2024, 8, 31))
    # VV alone: the water threshold reads it, and float radar is slow to fetch.
    assert reference.assets == event.assets == ("vv",)
