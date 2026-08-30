import h3
import pandas as pd
import pytest

from src.anonymize import anonymise_subsample

CELL = h3.latlng_to_cell(-33.56, 18.49, 8)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "notification_number": ["N123"],
            "reference_number": ["R456"],
            "latitude": [-33.56],
            "longitude": [18.49],
            "h3_level8_index": [CELL],
            "creation_timestamp": ["2020-03-14 09:23"],
            "completion_timestamp": ["2020-03-14 15:02"],
            "wind_timestamp": ["2020-03-14 09:00"],
            "Unnamed: 0": [99],
        }
    )


def test_anonymisation_removes_coordinates_and_direct_identifiers():
    anonymised, review = anonymise_subsample(_frame())

    removed = {
        "latitude",
        "longitude",
        "notification_number",
        "reference_number",
        "Unnamed: 0",
    }
    assert removed.isdisjoint(anonymised.columns)
    assert review.loc[0, "notification_number"] == "N123"
    assert review.loc[0, "reference_number"] == "R456"
    assert anonymised.loc[0, "surrogate_id"] == review.loc[0, "surrogate_id"]


def test_timestamps_are_floored_to_six_hour_buckets():
    anonymised, _ = anonymise_subsample(_frame())

    assert anonymised.loc[0, "creation_timestamp"] == pd.Timestamp("2020-03-14 06:00")
    assert anonymised.loc[0, "completion_timestamp"] == pd.Timestamp("2020-03-14 12:00")
    assert anonymised.loc[0, "wind_timestamp"] == pd.Timestamp("2020-03-14 06:00")


def test_resolution_eight_h3_location_is_preserved():
    anonymised, _ = anonymise_subsample(_frame())
    assert anonymised.loc[0, "h3_level8_index"] == CELL


def test_invalid_h3_location_is_rejected():
    frame = _frame()
    frame["h3_level8_index"] = "not-an-h3-cell"

    with pytest.raises(ValueError, match="resolution-8"):
        anonymise_subsample(frame)


def test_invalid_timestamp_is_rejected():
    frame = _frame()
    frame["creation_timestamp"] = "not-a-date"

    with pytest.raises(ValueError, match="creation_timestamp"):
        anonymise_subsample(frame)
