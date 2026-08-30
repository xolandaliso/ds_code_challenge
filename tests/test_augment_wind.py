from unittest.mock import patch

import pandas as pd
import pytest
import requests

from src.augment_wind import (
    WindDataError,
    detect_spreadsheet_engine,
    fetch_wind_workbook,
    join_wind_to_subsample,
    normalise_multistation_wind_frame,
    normalise_wind_frame,
)


def test_normalises_single_station_columns():
    raw = pd.DataFrame(
        {
            "Date": ["14/03/2020"],
            "Time": ["09:00"],
            "Wind Speed": [4.2],
            "Wind Direction": [315],
        }
    )

    result = normalise_wind_frame(raw)

    assert result.columns.tolist() == [
        "wind_timestamp",
        "wind_speed",
        "wind_direction",
    ]
    assert result.loc[0, "wind_speed"] == 4.2
    assert result.loc[0, "wind_direction"] == 315


def test_normalises_wide_multistation_layout():
    columns = pd.MultiIndex.from_tuples(
        [
            ("Date & Time", "Date & Time"),
            ("Atlantis AQM Site", "Wind Dir V"),
            ("Atlantis AQM Site", "Wind Speed V"),
            ("Other Site", "Wind Speed V"),
        ]
    )
    raw = pd.DataFrame([["2020-03-14 09:00", 315, 4.2, 8.0]], columns=columns)

    result = normalise_multistation_wind_frame(raw, "Atlantis")

    assert len(result) == 1
    assert result.loc[0, "wind_speed"] == 4.2
    assert result.loc[0, "wind_direction"] == 315


def test_detects_xlsx_container(tmp_path):
    workbook = tmp_path / "wind.xlsx"
    pd.DataFrame({"value": [1]}).to_excel(workbook, index=False)
    assert detect_spreadsheet_engine(workbook) == "openpyxl"


@patch("src.augment_wind.download")
def test_fetch_uses_valid_cache_after_download_failure(mock_download, tmp_path):
    mock_download.side_effect = requests.RequestException("offline")
    cache = tmp_path / "wind.xlsx"
    pd.DataFrame({"value": [1]}).to_excel(cache, index=False)

    result = fetch_wind_workbook(["https://example.test/wind"], cache)

    assert result == cache


@patch("src.augment_wind.download")
def test_fetch_fails_when_download_and_cache_are_unavailable(mock_download, tmp_path):
    mock_download.side_effect = requests.RequestException("offline")

    with pytest.raises(WindDataError, match="no valid cache"):
        fetch_wind_workbook(["https://example.test/wind"], tmp_path / "missing.xlsx")


def test_nearest_wind_join_preserves_original_request_order():
    requests_df = pd.DataFrame(
        {
            "id": [2, 1],
            "creation_timestamp": ["2020-03-14 10:05", "2020-03-14 09:05"],
        }
    )
    wind = pd.DataFrame(
        {
            "wind_timestamp": pd.to_datetime(["2020-03-14 09:00", "2020-03-14 10:00"]),
            "wind_speed": [3.0, 4.0],
            "wind_direction": [0, 315],
        }
    )

    result = join_wind_to_subsample(requests_df, wind, tolerance_minutes=15)

    assert result["id"].tolist() == [2, 1]
    assert result["wind_speed"].tolist() == [4.0, 3.0]
    assert result["wind_match_offset_minutes"].tolist() == [5.0, 5.0]


def test_unmatched_rate_above_configured_maximum_raises():
    requests_df = pd.DataFrame({"creation_timestamp": ["2020-03-15 09:00"]})
    wind = pd.DataFrame(
        {
            "wind_timestamp": pd.to_datetime(["2020-03-14 09:00"]),
            "wind_speed": [3.0],
            "wind_direction": [0],
        }
    )

    with pytest.raises(WindDataError, match="exceeds configured maximum"):
        join_wind_to_subsample(
            requests_df,
            wind,
            tolerance_minutes=15,
            max_unmatched_rate=0.05,
        )
