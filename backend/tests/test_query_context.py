"""Tests for reading location, time, metric and modality out of a question."""

from __future__ import annotations

from datetime import date

import pytest

from app.agents.agent import to_task_understanding
from app.agents.schemas import AgentTaskPlan
from app.controller.task_understanding.context import (
    extract_aoi,
    extract_context,
    extract_locations,
    extract_metrics,
    extract_modality,
    extract_time_range,
)


# ============================================================
# TIME
# ============================================================
@pytest.mark.parametrize(
    "query, start, end",
    [
        ("vegetation loss between 2023 and 2025", date(2023, 1, 1), date(2025, 12, 31)),
        ("from 2019 to 2021", date(2019, 1, 1), date(2021, 12, 31)),
        ("NDVI in June 2024", date(2024, 6, 1), date(2024, 6, 30)),
        ("water on 2024-08-22", date(2024, 8, 22), date(2024, 8, 22)),
        ("changes since 2020", date(2020, 1, 1), None),
        ("land cover before 2021-03-15", None, date(2021, 3, 15)),
    ],
)
def test_periods_are_read_from_dates_months_and_years(query, start, end):
    period = extract_time_range(query)
    assert (period.start, period.end) == (start, end)


@pytest.mark.parametrize(
    "query",
    [
        "Is there a river here?",
        "Pixel 2000 at 21.2030, band B8 over 2000 m",
        "within 2000 m of the river",
    ],
)
def test_numbers_that_are_not_years_are_not_read_as_years(query):
    assert extract_time_range(query) is None


TODAY = date(2026, 10, 26)


@pytest.mark.parametrize(
    "query, start, end",
    [
        # One day, however it is written; day first, as dates are written in India.
        ("NDVI in Pune on August 15, 2024", date(2024, 8, 15), date(2024, 8, 15)),
        ("NDVI on 15th Aug, 2024", date(2024, 8, 15), date(2024, 8, 15)),
        ("NDVI on 15 August 2024", date(2024, 8, 15), date(2024, 8, 15)),
        ("NDVI on 05/08/2024", date(2024, 8, 5), date(2024, 8, 5)),
        ("NDVI on 15-08-2024", date(2024, 8, 15), date(2024, 8, 15)),
        # A month that cannot come first is read the American way.
        ("NDVI on 08/15/2024", date(2024, 8, 15), date(2024, 8, 15)),
        ("water in 2024-08", date(2024, 8, 1), date(2024, 8, 31)),
        ("between 15/01/2020 and 20 March 2024", date(2020, 1, 15), date(2024, 3, 20)),
        # Indian seasons.
        ("flooding near Kochi in monsoon 2024", date(2024, 6, 1), date(2024, 9, 30)),
        ("2024 monsoon floods", date(2024, 6, 1), date(2024, 9, 30)),
        ("crops in kharif 2023", date(2023, 6, 1), date(2023, 10, 31)),
        ("crops in rabi 2023", date(2023, 11, 1), date(2024, 4, 30)),
        ("मानसून 2024 में बाढ़", date(2024, 6, 1), date(2024, 9, 30)),
        ("flooding in the last monsoon", date(2026, 6, 1), date(2026, 9, 30)),
        ("crops this rabi", date(2025, 11, 1), date(2026, 4, 30)),
        # Relative to today.
        ("flooding in Kochi last month", date(2026, 9, 1), date(2026, 9, 30)),
        ("vegetation in the past 3 months", date(2026, 7, 28), TODAY),
        ("water in the last 120 days", date(2026, 6, 28), TODAY),
        ("built-up area this year", date(2026, 1, 1), TODAY),
        ("what changed last year", date(2025, 1, 1), date(2025, 12, 31)),
        ("भोपाल में पिछले साल क्या बदलाव हुआ?", date(2025, 1, 1), date(2025, 12, 31)),
    ],
)
def test_days_seasons_and_relative_periods_are_read(query, start, end):
    period = extract_time_range(query, today=TODAY)
    assert (period.start, period.end) == (start, end)


def test_bare_winter_or_summer_is_not_a_period():
    # "winter wheat" names a crop, not a date.
    assert extract_time_range("winter wheat in Punjab", today=TODAY) is None
    assert extract_time_range("summer crops", today=TODAY) is None


def test_a_season_is_not_mistaken_for_a_place():
    assert "Monsoon" not in extract_locations("In Monsoon 2024 near Kochi")


# ============================================================
# LOCATION
# ============================================================
def test_a_named_part_of_the_scene_is_a_region():
    assert extract_aoi("NDVI in the north-western corner").region == "north_west"
    assert extract_aoi("the northern half of the image").region == "north"
    assert extract_aoi("count lakes in the top left quadrant").region == "north_west"
    assert extract_aoi("what is in the centre of the image").region == "centre"


def test_a_part_of_a_place_is_not_a_part_of_the_image():
    # "The northern part of Maharashtra" is about the state, not the scene.
    assert extract_aoi("Show the northern part of Maharashtra") is None


def test_a_bounding_box_and_lat_lon_ranges_become_an_area():
    assert extract_aoi("Map water for bbox 79.0, 21.1, 79.2, 21.3").bbox == [79.0, 21.1, 79.2, 21.3]
    area = extract_aoi("latitude 21.0 to 21.3, longitude 78.9 to 79.2")
    assert area.bbox == [78.9, 21.0, 79.2, 21.3]
    assert area.crs == "EPSG:4326"


def test_a_radius_around_a_point_becomes_a_square():
    area = extract_aoi("Find flooding within 5 km of 21.14 N, 79.08 E")
    west, south, east, north = area.bbox
    assert south == pytest.approx(21.14 - 5 / 111.32)
    assert north == pytest.approx(21.14 + 5 / 111.32)
    assert (west + east) / 2 == pytest.approx(79.08)


def test_place_names_are_kept_as_written_and_not_mistaken():
    assert extract_locations("What percentage of Nagpur is built-up?") == ["Nagpur"]
    assert extract_locations("floods over the Godavari basin") == ["Godavari"]
    assert extract_locations("NDVI of this Sentinel-2 image in June") == []


# ============================================================
# METRIC AND MODALITY
# ============================================================
def test_metrics_are_what_the_answer_should_lead_with():
    assert extract_metrics("What percentage of the scene is water?") == ["percentage"]
    assert extract_metrics("What is the total area under forest in hectares?") == ["area"]
    assert "count" in extract_metrics("How many lakes are there?")
    assert extract_metrics("Find areas affected by flooding") == []


@pytest.mark.parametrize(
    "query, modality",
    [
        ("Fuse the optical and SAR images", "optical+sar"),
        ("combine radar and optical data", "optical+sar"),
        ("water in this radar image", "sar"),
        ("RISAT backscatter", "sar"),
        ("true colour Sentinel-2 view", "optical"),
        ("Is it necessary to classify this?", None),
    ],
)
def test_the_sensor_a_question_speaks_of(query, modality):
    assert extract_modality(query) == modality


# ============================================================
# NOTHING THAT CHANGES A COMPUTATION COMES FROM A MODEL
# ============================================================
def test_a_models_places_add_to_the_reading_but_its_coordinates_cannot():
    plan = AgentTaskPlan(
        task="ndvi", tool="ndvi", locations=["Nagpur"], metrics=["mean", "not-a-metric"],
    )
    understanding = to_task_understanding(plan, "How healthy is the vegetation in the northern half?")

    context = understanding.context
    assert context.locations == ["Nagpur"]
    assert context.metrics == ["mean"]
    # The region comes from the sentence itself.
    assert context.aoi.region == "north"


def test_the_whole_context_in_one_call():
    context = extract_context(
        "What percentage of Nagpur lost vegetation in the south-east quadrant between 2023 and 2025?"
    )
    assert context.locations == ["Nagpur"]
    assert context.aoi.region == "south_east"
    assert context.time_range.describe() == "2023-01-01 to 2025-12-31"
    assert context.metrics == ["percentage"]
