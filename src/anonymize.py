'''
    task 5 sub-task 3 
        reduce spatial/temporal precision and isolate identifiers.
'''
from __future__ import annotations

import uuid
from collections.abc import Iterable

import h3
import pandas as pd

from src.settings import logger


def validate_h3_resolution(series: pd.Series, resolution: int = 8) -> None:
    '''
        confirm every H3 cell in the column is a valid cell at the expected

    '''
    invalid = []
    for value in series.dropna().astype(str).unique():
        try:
            if not h3.is_valid_cell(value) or h3.get_resolution(value) != resolution:
                invalid.append(value)
        except (TypeError, ValueError):
            invalid.append(value)
    if invalid:
        raise ValueError(
            f"Anonymised location requires valid resolution-{resolution} H3 cells; "
            f"invalid examples: {invalid[:3]}"
        )


def anonymise_subsample(
    df: pd.DataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    timestamp_columns: Iterable[str] = ("creation_timestamp", "completion_timestamp", "wind_timestamp"),
    hex_col: str = "h3_level8_index",
    direct_identifiers: Iterable[str] = ("notification_number", "reference_number"),
    drop_columns: Iterable[str] = ("Unnamed: 0",),
    time_bucket_hours: int = 6,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    '''
        return a publication table and a separately controlled review table

    '''
    if hex_col not in df.columns:
        raise KeyError(
            f"Expected '{hex_col}' before anonymisation; run the H3 join first"
        )
    validate_h3_resolution(df[hex_col])

    working = df.copy()
  
    working["surrogate_id"] = [str(uuid.uuid4()) for _ in range(len(working))]

    identifiers = [c for c in direct_identifiers if c in working.columns]
    review_columns = ["surrogate_id", *identifiers]
    manual_review = working[review_columns].copy()

    remove = {lat_col, lon_col, *identifiers, *drop_columns}
    anonymised = working.drop(columns=[c for c in remove if c in working.columns])

    for column in timestamp_columns:
        if column not in anonymised.columns:
            continue
        original_non_null = anonymised[column].notna()
        parsed = pd.to_datetime(anonymised[column], errors="coerce")
        if (original_non_null & parsed.isna()).any():
            raise ValueError(f"Column '{column}' contains invalid timestamps")

        # floor to a fixed 6-hour bucket (00:00/06:00/12:00/18:00) rather
        anonymised[column] = parsed.dt.floor(f"{time_bucket_hours}h")

    logger.info(
        f"Anonymised {len(anonymised)} rows; isolated direct identifiers for controlled review: {identifiers}"
    )
    return anonymised, manual_review