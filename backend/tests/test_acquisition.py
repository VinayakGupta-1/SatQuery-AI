"""Automatic imagery acquisition, entirely offline.

The catalogue, the token service and the geocoder are replaced by one fake
``request_json``; the remote band reader by a fake ``read_asset`` that returns
known pixel values. Everything between them -- choosing the place, planning the
windows, ranking passes, checking cloud on the pixels, mosaicking, removing the
reflectance offset, writing the GeoTIFF -- is the real code, and the files it
writes are read back through the project's own reader.
"""

from __future__ import annotations

import io
from datetime import date

import numpy
import pytest
from fastapi.testclient import TestClient

from app.acquisition import catalog, location, reader
from app.acquisition.catalog import SENTINEL1, SENTINEL2, Acquisition
from app.acquisition.location import (
    best_match,
    extent_km,
    parse_bbox,
    parse_point,
    point_in_query,
    resolve_area,
)
from app.acquisition.planner import choose_sensor, optical_assets, plan_acquisition
from app.acquisition.service import acquire, cloud_and_coverage, rank, utm_epsg
from app.acquisition.web import AcquisitionError
from app.api.store import task_store
from app.config.settings import get_settings, reset_settings
from app.controller.pipeline import SatQueryPipeline
from app.controller.task_understanding.context import extract_context, extract_periods
from app.controller.task_understanding.task_understanding import TaskUnderstanding
from app.main import create_app
from app.schemas.acquisition import AcquisitionReport
from app.tools.raster.inspection import describe_raster
from app.tools.raster.io import open_raster

TODAY = date(2026, 10, 17)
#: A box over Pune that every fake tile covers.
TILE = (73.0, 18.0, 75.0, 19.5)


def understand(query: str):
    return TaskUnderstanding().understand(query)


@pytest.fixture
def fetch_settings(monkeypatch, tmp_path):
    """Fetching on, with a 1 km default area so test rasters stay small."""
    monkeypatch.setenv("SATQUERY_FETCH_ENABLED", "1")
    monkeypatch.setenv("SATQUERY_FETCH_DEFAULT_EXTENT_KM", "1")
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "storage"))
    reset_settings()
    yield get_settings()
    reset_settings()


# ============================================================
# FAKES
# ============================================================
def feature(
    item_id: str,
    day: str,
    collection=SENTINEL2,
    platform: str = "Sentinel-2A",
    cloud: float | None = 1.0,
    box: tuple[float, float, float, float] = TILE,
    baseline: str = "05.11",
):
    west, south, east, north = box
    properties = {
        "datetime": f"{day}T05:30:00Z",
        "platform": platform,
        "proj:epsg": 32643,
        "s2:processing_baseline": baseline,
    }
    if cloud is not None:
        properties["eo:cloud_cover"] = cloud
    return {
        "id": item_id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
        },
        "properties": properties,
        "assets": {
            key: {"href": f"https://example.test/{item_id}/{key}.tif"}
            for key, _ in collection.bands
        },
    }


class FakeWeb:
    """Answers catalogue searches, token requests and geocoder lookups."""

    def __init__(self, features=(), places=None):
        self.features = list(features)
        self.places = places or {}
        self.searches: list[dict] = []

    def __call__(self, url, params=None, body=None, timeout=60):
        if url.endswith("/search") and body is not None:
            self.searches.append(body)
            start, end = (part[:10] for part in body["datetime"].split("/"))
            chosen = [
                f for f in self.features
                if f["id"].startswith(body["collections"][0])
                and start <= f["properties"]["datetime"][:10] <= end
            ]
            return {"features": chosen}
        if "/token/" in url:
            return {"token": "sig=abc", "msft:expiry": "2099-01-01T00:00:00Z"}
        if params and "q" in params:
            return self.places.get(params["q"], [])
        raise AssertionError(f"unexpected request to {url}")


def s2(item_id: str, day: str, **kwargs):
    return feature(f"sentinel-2-l2a-{item_id}", day, **kwargs)


def s1(item_id: str, day: str, **kwargs):
    return feature(
        f"sentinel-1-rtc-{item_id}", day, collection=SENTINEL1, platform="SENTINEL-1A",
        cloud=None, **kwargs,
    )


def fake_pixels(cloudy_items=()):
    """A ``read_asset`` returning fixed values per band.

    Red DN 1500 and NIR DN 4000 carry the +1000 offset, so after it is removed
    NDVI is (3000 - 500) / (3000 + 500) = 0.714. Items named in
    ``cloudy_items`` are cloud (SCL 9) over the whole area.
    """
    values = {"B02": 1300, "B03": 1400, "B04": 1500, "B08": 4000, "B11": 2500, "SCL": 4}

    def read(href, grid, categorical, nodata):
        item_id, key = href.split("/")[-2], href.split("/")[-1].split(".")[0]
        shape = (grid.height, grid.width)
        if key in ("vv", "vh"):
            return numpy.full(shape, 0.01 if key == "vv" else 0.002, dtype="float32")
        if key == "SCL" and item_id in cloudy_items:
            return numpy.full(shape, 9, dtype="uint8")
        dtype = "uint8" if key == "SCL" else "uint16"
        return numpy.full(shape, values[key], dtype=dtype)

    return read


@pytest.fixture
def network(monkeypatch):
    """Install a FakeWeb and fake pixels; returns the FakeWeb to configure."""
    web = FakeWeb()
    monkeypatch.setattr(location, "request_json", web)
    monkeypatch.setattr(catalog, "request_json", web)
    monkeypatch.setattr(reader, "read_asset", fake_pixels())
    monkeypatch.setattr(location, "_geocode_cache", {})
    monkeypatch.setattr(location, "_last_geocode", 0.0)
    return web


# ============================================================
# LOCATION
# ============================================================
def test_points_and_boxes_are_parsed():
    assert parse_point("18.52, 73.85") == (73.85, 18.52)
    assert parse_point("18.52 S, 73.85 W") == (-73.85, -18.52)
    assert parse_point("Pune") is None
    assert parse_bbox("73.8, 18.4, 73.9, 18.6") == [73.8, 18.4, 73.9, 18.6]
    assert parse_bbox("73.9, 18.6, 73.8, 18.4") == [73.8, 18.4, 73.9, 18.6]
    assert parse_bbox("1, 2, 3") is None
    assert point_in_query("What is near 18.5204, 73.8567 today?") == (73.8567, 18.5204)
    assert point_in_query("Classify the land cover in 2024") is None


def test_location_field_wins_over_the_question(fetch_settings, network):
    area = resolve_area("18.52, 73.85", "Vegetation in Mumbai?", extract_context("Vegetation in Mumbai?"), fetch_settings)
    assert area.source == "location field"
    assert area.name == "18.5200°N, 73.8500°E"
    width, height = extent_km(area.bbox)
    assert width == pytest.approx(1.0, rel=0.01) and height == pytest.approx(1.0, rel=0.01)


def test_place_names_are_geocoded_and_large_places_cut_to_the_limit(fetch_settings, network):
    network.places["Pune"] = [{
        "category": "place", "lat": "18.52", "lon": "73.85",
        "boundingbox": ["18.36", "18.68", "73.69", "74.01"],
        "display_name": "Pune, Maharashtra, India",
    }]
    query = "How healthy is the vegetation in Pune?"
    area = resolve_area(None, query, extract_context(query), fetch_settings)
    assert area.source == "geocoded"
    assert area.name == "Pune, Maharashtra, India"
    assert max(extent_km(area.bbox)) == pytest.approx(fetch_settings.fetch_max_extent_km, rel=0.01)
    assert "20 km square" in area.notes[0]


def test_photon_answers_when_nominatim_refuses(fetch_settings, monkeypatch):
    def web(url, params=None, body=None, timeout=60):
        if "nominatim" in url:
            raise AcquisitionError("nominatim.openstreetmap.org answered HTTP 429; try again shortly.")
        assert "photon" in url
        return {"features": [
            {"geometry": {"coordinates": [73.40, 18.75]},
             "properties": {"osm_key": "place", "name": "Lonavala", "state": "Maharashtra", "country": "India"}},
            {"geometry": {"coordinates": [73.41, 18.76]},
             "properties": {"osm_key": "boundary", "name": "Lonavala Municipal Council", "state": "Maharashtra",
                            "country": "India", "extent": [73.35, 18.80, 73.45, 18.70]}},
        ]}

    monkeypatch.setattr(location, "request_json", web)
    monkeypatch.setattr(location, "_geocode_cache", {})
    monkeypatch.setattr(location, "_last_geocode", 0.0)
    query = "How healthy is the vegetation in Lonavala?"
    area = resolve_area(None, query, extract_context(query), fetch_settings)
    assert area.name == "Lonavala, Maharashtra, India"
    west, south, east, north = area.bbox
    assert west < 73.40 < east and south < 18.75 < north


def test_photon_lookalikes_are_not_taken_for_the_place(fetch_settings, monkeypatch):
    def web(url, params=None, body=None, timeout=60):
        if "nominatim" in url:
            raise AcquisitionError("nominatim.openstreetmap.org answered HTTP 429; try again shortly.")
        return {"features": [
            {"geometry": {"coordinates": [47.4, 42.6]},
             "properties": {"osm_key": "place", "name": "Chilikar", "state": "Dagestan", "country": "Russia"}},
        ]}

    monkeypatch.setattr(location, "request_json", web)
    monkeypatch.setattr(location, "_geocode_cache", {})
    monkeypatch.setattr(location, "_last_geocode", 0.0)
    with pytest.raises(AcquisitionError) as raised:
        resolve_area("Chilikx", "NDVI?", extract_context("NDVI?"), fetch_settings)
    assert raised.value.status == "needs_location"
    # A name the built-in list knows never reaches Photon at all.
    area = resolve_area("Chilika", "NDVI?", extract_context("NDVI?"), fetch_settings)
    assert area.name.startswith("Chilika Lake")


def test_both_geocoders_refusing_suggests_coordinates(fetch_settings, monkeypatch):
    def web(url, params=None, body=None, timeout=60):
        raise AcquisitionError(f"{url.split('/')[2]} answered HTTP 429; try again shortly.")

    monkeypatch.setattr(location, "request_json", web)
    monkeypatch.setattr(location, "_geocode_cache", {})
    monkeypatch.setattr(location, "_last_geocode", 0.0)
    with pytest.raises(AcquisitionError) as raised:
        resolve_area("Nowhereville", "NDVI?", extract_context("NDVI?"), fetch_settings)
    assert "18.52, 73.85" in str(raised.value)
    assert "photon.komoot.io" in str(raised.value)


@pytest.mark.parametrize("place", ["Pune", "pune", "पुणे"])
def test_well_known_places_work_when_both_geocoders_refuse(fetch_settings, monkeypatch, place):
    def web(url, params=None, body=None, timeout=60):
        raise AcquisitionError(f"{url.split('/')[2]} answered HTTP 429; try again shortly.")

    monkeypatch.setattr(location, "request_json", web)
    monkeypatch.setattr(location, "_geocode_cache", {})
    monkeypatch.setattr(location, "_last_geocode", 0.0)
    area = resolve_area(place, "NDVI?", extract_context("NDVI?"), fetch_settings)
    assert area.name.startswith("Pune, ")
    assert "built-in list" in area.notes[0]
    west, south, east, north = area.bbox
    assert west < 73.85 < east and south < 18.52 < north


def test_area_features_are_preferred_to_points():
    station = {"category": "railway", "display_name": "Hosur station"}
    town = {"category": "boundary", "display_name": "Hosur"}
    assert best_match([station, town]) is town
    assert best_match([station]) is station


def test_no_place_asks_for_one(fetch_settings, network):
    query = "How healthy is the vegetation?"
    with pytest.raises(AcquisitionError) as raised:
        resolve_area(None, query, extract_context(query), fetch_settings)
    assert raised.value.status == "needs_location"


def test_unknown_place_asks_for_another(fetch_settings, network):
    with pytest.raises(AcquisitionError) as raised:
        resolve_area("Atlantis", "NDVI?", extract_context("NDVI?"), fetch_settings)
    assert raised.value.status == "needs_location"
    assert "Atlantis" in str(raised.value)


# ============================================================
# PLANNING
# ============================================================
@pytest.mark.parametrize(
    "query, sensor",
    [
        ("How healthy is the vegetation in Pune?", "optical"),
        ("Find the areas affected by flooding near Kochi", "sar"),
        ("Map the flooding near Kochi with optical imagery", "optical"),
        ("Fuse optical and SAR to map water near Kochi", "fusion"),
        ("Show the radar backscatter over Kochi", "sar"),
    ],
)
def test_the_task_decides_the_sensor(query, sensor):
    assert choose_sensor(understand(query)) == sensor


def test_only_the_bands_a_task_reads_are_fetched():
    assert optical_assets(understand("NDVI of Pune")) == ("B02", "B03", "B04", "B08", "SCL")
    assert "B11" in optical_assets(understand("Where are the built-up areas in Pune?"))
    assert "B11" in optical_assets(understand("How much has urban area grown in Pune since 2018?"))
    assert "B11" not in optical_assets(understand("How much forest was lost in Pune since 2018?"))


def test_a_single_scene_comes_from_the_recent_past_or_the_named_period(fetch_settings):
    plan = plan_acquisition(understand("NDVI of Pune"), fetch_settings, TODAY)
    (request,) = plan.requests
    assert (request.start, request.end) == (date(2026, 6, 19), TODAY)

    plan = plan_acquisition(understand("NDVI of Pune in March 2024"), fetch_settings, TODAY)
    (request,) = plan.requests
    assert (request.start, request.end) == (date(2024, 3, 1), date(2024, 3, 31))


@pytest.mark.parametrize(
    "query, before, after",
    [
        (
            "Has vegetation been lost in Pune between 2019 and 2025?",
            (date(2019, 1, 1), date(2019, 12, 31)),
            (date(2025, 1, 1), date(2025, 12, 31)),
        ),
        (
            "How much has the lake shrunk in Pune since 2018?",
            (date(2018, 1, 1), date(2018, 12, 31)),
            (date(2026, 6, 19), TODAY),
        ),
        (
            "Detect changes in Pune",
            (date(2025, 6, 19), date(2025, 10, 17)),
            (date(2026, 6, 19), TODAY),
        ),
    ],
)
def test_change_questions_get_a_before_and_an_after_window(fetch_settings, query, before, after):
    plan = plan_acquisition(understand(query), fetch_settings, TODAY)
    assert plan.kind == "change"
    first, second = plan.requests
    assert (first.role, first.start, first.end) == ("before", *before)
    assert (second.role, second.start, second.end) == ("after", *after)


def test_two_periods_are_kept_apart():
    periods = extract_periods("between March 2020 and 2024")
    assert [(p.start, p.end) for p in periods] == [
        (date(2020, 3, 1), date(2020, 3, 31)),
        (date(2024, 1, 1), date(2024, 12, 31)),
    ]


def test_a_future_period_has_no_imagery(fetch_settings):
    with pytest.raises(AcquisitionError) as raised:
        plan_acquisition(understand("NDVI of Pune in 2030"), fetch_settings, TODAY)
    assert raised.value.status == "unavailable"


# ============================================================
# CATALOGUE AND RANKING
# ============================================================
def test_coverage_counts_the_area_inside_the_tiles():
    tile = feature("t", "2026-01-01", box=(0.0, 0.0, 1.0, 1.0))["geometry"]
    assert catalog.coverage([0.0, 0.0, 1.0, 1.0], [tile]) == 1.0
    assert catalog.coverage([0.5, 0.0, 1.5, 1.0], [tile]) == pytest.approx(0.5)
    assert catalog.coverage([2.0, 2.0, 3.0, 3.0], [tile]) == 0.0


def test_tiles_of_one_pass_are_grouped_and_cover_together(fetch_settings):
    left = catalog._item(feature("a", "2026-01-01", box=(0.0, 0.0, 0.5, 1.0)), SENTINEL2)
    right = catalog._item(feature("b", "2026-01-01", box=(0.5, 0.0, 1.0, 1.0)), SENTINEL2)
    other_day = catalog._item(feature("c", "2026-01-06", box=(0.0, 0.0, 1.0, 1.0)), SENTINEL2)
    groups = catalog.group_acquisitions([left, right, other_day], [0.0, 0.0, 1.0, 1.0])
    by_day = {group.day: group for group in groups}
    assert len(by_day[date(2026, 1, 1)].items) == 2
    assert by_day[date(2026, 1, 1)].coverage == 1.0


def test_items_missing_a_band_are_dropped():
    broken = feature("x", "2026-01-01")
    del broken["assets"]["B08"]
    assert catalog._item(broken, SENTINEL2) is None


@pytest.mark.parametrize("href", ["/etc/passwd", "file:///C:/secrets.tif", "http://example.test/B08.tif"])
def test_only_https_assets_are_ever_read(href):
    item = feature("x", "2026-01-01")
    item["assets"]["B08"]["href"] = href
    assert catalog._item(item, SENTINEL2) is None


def test_search_asks_for_the_cloud_limit_only_on_optical(fetch_settings, network):
    catalog.search(SENTINEL2, list(TILE), date(2026, 1, 1), date(2026, 2, 1), fetch_settings)
    catalog.search(SENTINEL1, list(TILE), date(2026, 1, 1), date(2026, 2, 1), fetch_settings)
    optical, radar = network.searches
    assert optical["query"] == {"eo:cloud_cover": {"lte": fetch_settings.fetch_max_cloud_percent}}
    assert "query" not in radar
    assert optical["datetime"] == "2026-01-01T00:00:00Z/2026-02-01T23:59:59Z"


def test_planetary_computer_urls_are_signed_once_per_collection(fetch_settings, monkeypatch):
    calls = []

    def token_service(url, params=None, body=None, timeout=60):
        calls.append(url)
        return {"token": "sig=abc", "msft:expiry": "2099-01-01T00:00:00Z"}

    monkeypatch.setattr(catalog, "request_json", token_service)
    monkeypatch.setattr(catalog, "_tokens", {})
    href = "https://sentinel2l2a01.blob.core.windows.net/x/B04.tif"
    assert catalog.sign(href, SENTINEL2, fetch_settings) == href + "?sig=abc"
    catalog.sign(href, SENTINEL2, fetch_settings)
    assert len(calls) == 1
    assert catalog.sign("https://example.test/B04.tif", SENTINEL2, fetch_settings).endswith("B04.tif")


def _acquisition(day: str, cloud: float, covered: float = 1.0) -> Acquisition:
    item = catalog._item(feature(day, day, cloud=cloud), SENTINEL2)
    return Acquisition(items=[item], coverage=covered)


def test_ranking_prefers_coverage_then_clear_sky_then_recency():
    partial = _acquisition("2026-10-10", cloud=0.0, covered=0.7)
    hazy = _acquisition("2026-10-12", cloud=30.0)
    clear_old = _acquisition("2026-09-01", cloud=2.0)
    clear_new = _acquisition("2026-10-01", cloud=4.0)
    useless = _acquisition("2026-10-15", cloud=0.0, covered=0.2)
    ranked = rank([partial, hazy, clear_old, clear_new, useless])
    assert [a.day.isoformat() for a in ranked] == ["2026-10-01", "2026-09-01", "2026-10-12", "2026-10-10"]


def test_before_scenes_are_matched_to_the_season_of_the_after_scene():
    january = _acquisition("2019-01-10", cloud=1.0)
    june = _acquisition("2019-06-10", cloud=1.0)
    december = _acquisition("2019-12-20", cloud=1.0)
    ranked = rank([june, january, december], season_of=date(2025, 12, 23))
    assert ranked[0] is december
    assert ranked[1] is january


def test_utm_zone_and_cloud_measures():
    assert utm_epsg(73.85, 18.52) == 32643
    assert utm_epsg(-43.2, -22.9) == 32723
    scl = numpy.array([[0, 4, 9, 4]], dtype="uint8")
    cloud, covered = cloud_and_coverage(scl)
    assert cloud == pytest.approx(1 / 3) and covered == 0.75


# ============================================================
# END TO END
# ============================================================
def test_a_scene_is_fetched_harmonised_and_written(fetch_settings, network, tmp_path):
    network.features = [s2("old", "2026-09-01"), s2("new", "2026-10-15")]
    outcome = acquire(
        understand("How healthy is the vegetation near 18.52, 73.85?"),
        None, str(tmp_path / "fetched"), fetch_settings, today=TODAY,
    )

    assert outcome.report.status == "fetched", outcome.report.message
    (image,) = outcome.images
    assert image.scene.item_ids == ["sentinel-2-l2a-new"]
    assert image.scene.acquired == "2026-10-15"
    assert image.scene.area_cloud_fraction == 0.0
    assert image.scene.bands == ["B02", "B03", "B04", "B08", "SCL"]

    dataset = open_raster(image.path)
    bands = {band.name: band for band in dataset.bands}
    # The +1000 offset of processing baseline 05.11 is removed.
    assert int(bands["B04"].values[0]) == 500
    assert int(bands["B08"].values[0]) == 3000
    assert int(bands["SCL"].values[0]) == 4
    assert dataset.georeference.crs == "EPSG:32643"

    metadata = describe_raster(image.path)
    assert metadata.modality == "optical"
    assert metadata.sensor == "sentinel2"
    assert metadata.acquisition_date == date(2026, 10, 15)
    assert {"red", "nir"} <= set(metadata.bands)


def test_older_baselines_keep_their_values(fetch_settings, network, tmp_path):
    network.features = [s2("legacy", "2021-05-01", baseline="02.09")]
    outcome = acquire(
        understand("NDVI near 18.52, 73.85 in May 2021"),
        None, str(tmp_path), fetch_settings, today=TODAY,
    )
    dataset = open_raster(outcome.images[0].path)
    assert int(next(b for b in dataset.bands if b.name == "B04").values[0]) == 1500


def test_a_cloudy_leader_is_passed_over_for_a_clear_scene(fetch_settings, network, monkeypatch, tmp_path):
    # The catalogue calls the newest tile clear, but it is cloud over the area.
    network.features = [s2("clouded", "2026-10-15", cloud=1.0), s2("clear", "2026-10-01", cloud=3.0)]
    monkeypatch.setattr(reader, "read_asset", fake_pixels(cloudy_items={"sentinel-2-l2a-clouded"}))
    outcome = acquire(understand("NDVI near 18.52, 73.85"), None, str(tmp_path), fetch_settings, today=TODAY)
    assert outcome.images[0].scene.item_ids == ["sentinel-2-l2a-clear"]


def test_a_change_question_gets_two_scenes_on_one_grid(fetch_settings, network, tmp_path):
    network.features = [
        s2("b-summer", "2019-06-01"), s2("b-winter", "2019-12-10"),
        s2("a-winter", "2025-12-23"),
    ]
    outcome = acquire(
        understand("Has vegetation been lost near 18.52, 73.85 between 2019 and 2025?"),
        None, str(tmp_path), fetch_settings, today=TODAY,
    )
    before, after = outcome.images
    assert (before.scene.role, after.scene.role) == ("before", "after")
    assert before.scene.acquired == "2019-12-10"  # same season as the after scene
    first, second = open_raster(before.path), open_raster(after.path)
    assert first.georeference.transform == second.georeference.transform
    assert (first.width, first.height) == (second.width, second.height)


def test_fusion_pairs_optical_with_the_nearest_radar_pass(fetch_settings, network, tmp_path):
    network.features = [
        s2("opt", "2026-09-10"),
        s1("far", "2026-08-01"),
        s1("near", "2026-09-14"),
    ]
    outcome = acquire(
        understand("Fuse optical and SAR to map water near 18.52, 73.85"),
        None, str(tmp_path), fetch_settings, today=TODAY,
    )
    optical, radar = outcome.images
    assert optical.scene.modality == "optical" and radar.scene.modality == "sar"
    assert radar.scene.item_ids == ["sentinel-1-rtc-near"]
    assert describe_raster(radar.path).modality == "sar"


def test_an_empty_catalogue_says_what_was_searched(fetch_settings, network, tmp_path):
    outcome = acquire(understand("NDVI near 18.52, 73.85"), None, str(tmp_path), fetch_settings, today=TODAY)
    assert outcome.report.status == "unavailable"
    assert "Sentinel-2 L2A" in outcome.report.message
    assert "2026-06-19" in outcome.report.message
    assert outcome.images == []


def test_fetching_can_be_switched_off(fetch_settings, network, tmp_path, monkeypatch):
    fetch_settings.fetch_enabled = False
    outcome = acquire(understand("NDVI near 18.52, 73.85"), None, str(tmp_path), fetch_settings, today=TODAY)
    assert outcome.report.status == "failed"
    assert "turned off" in outcome.report.message


# ============================================================
# PIPELINE AND API
# ============================================================
def test_the_pipeline_masks_cloud_on_fetched_scenes(fetch_settings, network, tmp_path):
    network.features = [s2("new", "2026-10-15")]
    from app.api.tasks import _fetcher

    summaries = []
    run = SatQueryPipeline().run(
        query="How healthy is the vegetation near 18.52, 73.85?",
        images=[],
        output_directory=str(tmp_path / "out"),
        acquire=_fetcher("task_fetch", None, summaries),
    )
    assert run.status == "success", run.final.answer
    assert run.configuration.resolved_parameters["mask_band"] == "SCL"
    assert run.execution.output["statistics"]["mean"] == pytest.approx(0.714, abs=0.001)
    assert run.acquisition.status == "fetched"
    assert [event.stage for event in run.trace][:2] == ["understanding", "acquisition"]
    assert summaries[0].sensor == "sentinel2"


@pytest.mark.parametrize(
    "status, outcome",
    [("needs_location", "needs_input"), ("unavailable", "imagery_unavailable")],
)
def test_a_failed_fetch_is_the_answer(status, outcome):
    report = AcquisitionReport(status=status, message="Name a place to look at.")
    run = SatQueryPipeline().run(
        query="How healthy is the vegetation?", images=[], acquire=lambda understanding: ([], report)
    )
    assert run.outcome == outcome
    assert run.status == "needs_clarification"
    assert run.final.answer == "Name a place to look at."
    assert run.clarification == "Name a place to look at."
    assert run.execution is None


def test_nothing_is_fetched_for_a_question_that_was_not_understood():
    calls = []

    def acquirer(understanding):
        calls.append(understanding)
        return [], AcquisitionReport(status="fetched")

    run = SatQueryPipeline().run(
        query="Tell me something interesting about Pune", images=[], acquire=acquirer
    )
    assert calls == []
    assert run.acquisition is None
    assert run.status == "needs_clarification"


def test_surface_water_questions_are_read_as_ndwi():
    assert understand("Map the surface water around Chilika Lake in March 2024").task_type == "ndwi"


def test_the_api_fetches_when_no_file_is_sent(fetch_settings, network):
    network.features = [s2("new", "2026-10-15")]
    task_store.clear()
    with TestClient(create_app()) as client:
        capabilities = client.get("/api/capabilities").json()
        response = client.post(
            "/api/tasks",
            data={"query": "How healthy is the vegetation?", "location": "18.52, 73.85"},
        )
    task_store.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success", body["answer"]
    assert body["acquisition"]["status"] == "fetched"
    assert body["acquisition"]["place_source"] == "location field"
    assert body["acquisition"]["scenes"][0]["acquired"] == "2026-10-15"
    assert body["images"][0]["filename"] == "Sentinel-2 L2A · 2026-10-15"
    assert body["images"][0]["acquisition_date"] == "2026-10-15"
    # Remote reads need GDAL, so only the rasterio backend advertises fetching.
    assert capabilities["auto_fetch"] == capabilities["backend"]["supports_compressed_geotiff"]


def test_the_api_asks_for_a_place_when_none_is_named(fetch_settings, network):
    task_store.clear()
    with TestClient(create_app()) as client:
        response = client.post("/api/tasks", data={"query": "How healthy is the vegetation?"})
    task_store.clear()
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "needs_clarification"
    assert body["outcome"] == "needs_input"
    assert "does not say where to look" in body["answer"]
    assert body["acquisition"]["status"] == "needs_location"


def test_uploads_still_take_precedence(fetch_settings, network, sentinel2_scene):
    with open(sentinel2_scene, "rb") as handle:
        content = handle.read()
    task_store.clear()
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/tasks",
            data={"query": "Calculate NDVI in Pune"},
            files=[("files", ("scene.tif", io.BytesIO(content), "image/tiff"))],
        )
    task_store.clear()
    body = response.json()
    assert body["status"] == "success"
    assert body["acquisition"] is None
    assert network.searches == []
