import json
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point, Polygon, mapping

from src.subsample_atlantis import (
    download_official_suburbs,
    filter_requests_near_suburb,
    get_suburb_centroid,
    load_official_suburbs,
)


def _suburbs() -> gpd.GeoDataFrame:
    polygon = Polygon(
        [(18.48, -33.57), (18.50, -33.57), (18.50, -33.55), (18.48, -33.55)]
    )
    return gpd.GeoDataFrame(
        {"OFC_SBRB_NAME": ["ROBINVALE"]}, geometry=[polygon], crs="EPSG:4326"
    )


@patch("src.subsample_atlantis.requests.get")
def test_download_requests_geojson_in_wgs84(mock_get):
    response = MagicMock()
    response.json.return_value = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": None}],
    }
    mock_get.return_value = response

    result = download_official_suburbs("https://example.test/query", "NAME")

    assert result["features"]
    kwargs = mock_get.call_args.kwargs
    assert kwargs["params"]["where"] == "1=1"
    assert kwargs["params"]["outFields"] == "NAME"
    assert kwargs["params"]["outSR"] == "4326"
    assert kwargs["params"]["f"] == "geojson"
    response.raise_for_status.assert_called_once()


def test_centroid_is_computed_case_insensitively_in_metric_crs():
    centroid = get_suburb_centroid(
        _suburbs(), "robinvale", "OFC_SBRB_NAME", "EPSG:32734"
    )

    assert centroid.crs.to_string() == "EPSG:32734"
    assert isinstance(centroid.iloc[0], Point)


def test_filter_selects_only_points_inside_metric_radius():
    centroid = gpd.GeoSeries([Point(18.49, -33.56)], crs="EPSG:4326").to_crs(
        "EPSG:32734"
    )
    requests_df = pd.DataFrame(
        {
            "id": ["near", "far", "invalid"],
            "latitude": [-33.56, -33.61, "bad"],
            "longitude": [18.49, 18.49, 18.49],
        }
    )

    result = filter_requests_near_suburb(
        requests_df, centroid, "latitude", "longitude", 1852
    )

    assert result["id"].tolist() == ["near"]
    assert "geometry" not in result.columns


@patch("src.subsample_atlantis.download_official_suburbs")
def test_cached_suburbs_are_used_when_download_fails(mock_download, tmp_path):
    mock_download.side_effect = requests.RequestException("service unavailable")
    polygon = _suburbs().geometry.iloc[0]
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"OFC_SBRB_NAME": "ROBINVALE"},
                "geometry": mapping(polygon),
            }
        ],
    }
    cache = tmp_path / "suburbs.geojson"
    cache.write_text(json.dumps(payload))

    result = load_official_suburbs("https://example.test/query", cache)

    assert len(result) == 1
    assert result.loc[0, "OFC_SBRB_NAME"] == "ROBINVALE"
