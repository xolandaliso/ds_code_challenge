import h3
import pandas as pd
import pytest

from src.transform_join import JoinThresholdExceededError, join_service_requests_to_hex

CONFIG = {
    "columns": {
        "latitude": "latitude",
        "longitude": "longitude",
        "output_index": "h3_level8_index",
    },
    "h3": {"resolution": 8, "null_geolocation_index": "0"},
    "join_error_threshold": 0.02,
}

LAT, LON = -33.9, 18.4
CELL = h3.latlng_to_cell(LAT, LON, 8)


def test_valid_coordinate_gets_expected_h3_index():
    source = pd.DataFrame({"latitude": [LAT], "longitude": [LON]})

    result, report = join_service_requests_to_hex(source, CONFIG, {CELL})

    assert result.loc[0, "h3_level8_index"] == CELL
    assert report.joined_rows == 1
    assert report.failed_rows == 0


def test_missing_coordinates_receive_zero_without_counting_as_failure():
    source = pd.DataFrame({"latitude": [None, LAT], "longitude": [None, None]})

    result, report = join_service_requests_to_hex(source, CONFIG, {CELL})

    assert result["h3_level8_index"].tolist() == ["0", "0"]
    assert report.null_geolocation_rows == 2
    assert report.failure_rate == 0


def test_invalid_non_null_coordinates_are_explicit_failures():
    config = {**CONFIG, "join_error_threshold": 1.0}
    source = pd.DataFrame({"latitude": ["bad"], "longitude": [LON]})

    result, report = join_service_requests_to_hex(source, config, {CELL})

    assert result.loc[0, "h3_level8_index"] == "join_failed"
    assert report.failed_rows == 1


def test_valid_cell_outside_city_is_retained_but_reported_as_failure():
    config = {**CONFIG, "join_error_threshold": 1.0}
    source = pd.DataFrame({"latitude": [LAT], "longitude": [LON]})

    result, report = join_service_requests_to_hex(source, config, set())

    assert result.loc[0, "h3_level8_index"] == CELL
    assert report.failed_rows == 1
    assert report.joined_rows == 0


def test_failure_rate_above_threshold_raises():
    source = pd.DataFrame({"latitude": [LAT], "longitude": [LON]})
    with pytest.raises(JoinThresholdExceededError, match="exceeds configured"):
        join_service_requests_to_hex(source, CONFIG, set())


def test_missing_configured_coordinate_column_raises():
    source = pd.DataFrame({"latitude": [LAT]})
    with pytest.raises(KeyError, match="longitude"):
        join_service_requests_to_hex(source, CONFIG, {CELL})
