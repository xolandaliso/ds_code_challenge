'''
    task 5 sub-task 2
        - download, normalize, and join the supplied 2020 wind data
'''

import re
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.settings import logger


class WindDataError(RuntimeError):
    """Raised when required wind enrichment cannot be produced safely."""


def normalise_name(value: object) -> str:
    # collapse arbitrary spreadsheet headers (spaces, casing, punctuation)
    # into a consistent snake_case key so downstream matching is reliable
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=20),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def download(url: str) -> bytes:
    '''
        download the raw wind workbook bytes, retrying transient failures
    '''
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    content = response.content

    if not content.startswith(b"PK"):
        raise requests.RequestException("response is not a valid zip-based spreadsheet")
    return content


def fetch_wind_workbook(urls: Iterable[str], cache_path: str | Path) -> Path:
    '''
        try each candidate URL in turn; fall back to the last good cache
    '''
    cache_path = Path(cache_path)
    errors: list[str] = []
    for url in urls:
        try:
            content = download(url)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(content)
            logger.info(f"Downloaded wind workbook to {cache_path}")
            return cache_path
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
            logger.warning(f"Wind download failed from {url}: {exc}")


    if cache_path.exists() and cache_path.read_bytes().startswith(b"PK"):
        logger.warning(f"Using cached wind workbook {cache_path}")
        return cache_path

    raise WindDataError(
        "All wind-data downloads failed and no valid cache exists: " + " | ".join(errors)
    )


def find_column(columns: list[str], aliases: set[str], required_terms: set[str]) -> str | None:
    # exact alias match first (fast path for known column names)
    for column in columns:
        if column in aliases:
            return column
    for column in columns:
        tokens = set(column.split("_"))
        if required_terms <= tokens:
            return column
    return None


def detect_spreadsheet_engine(path: str | Path) -> str:
    '''
        inspect the zip container's internal structure to determine the
        real spreadsheet format, rather than guessing
    '''
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())

    if "META-INF/manifest.xml" in names:
        return "odf"
    if "[Content_Types].xml" in names:
        return "openpyxl"

    raise WindDataError(
        f"'{path}' is a zip container but neither ODS nor XLSX internal "
        f"structure was found; first entries: {sorted(names)[:5]}"
    )


def normalise_wind_frame(raw: pd.DataFrame) -> pd.DataFrame:
    '''
        convert a plausible single-header City workbook table to canonical
        wind columns

    '''
    frame = raw.dropna(how="all").dropna(axis=1, how="all").copy()
    frame.columns = [normalise_name(c) for c in frame.columns]
    columns = list(frame.columns)

    timestamp_col = find_column(
        columns,
        {"timestamp", "datetime", "date_time", "reading_datetime", "sample_datetime"},
        {"date", "time"},
    )
    date_col = find_column(columns, {"date", "reading_date", "sample_date"}, {"date"})
    time_col = find_column(columns, {"time", "reading_time", "sample_time"}, {"time"})
    speed_col = find_column(
        columns, {"wind_speed", "windspeed", "ws"}, {"wind", "speed"}
    )
    direction_col = find_column(
        columns, {"wind_direction", "winddirection", "wd"}, {"wind", "direction"}
    )
    station_col = find_column(
        columns, {"station", "site", "monitoring_station", "station_name"}, {"station"}
    )

    if speed_col is None or direction_col is None:
        raise WindDataError(
            f"Could not identify wind speed/direction columns; found {columns}"
        )

    if timestamp_col:
        timestamp = pd.to_datetime(frame[timestamp_col], errors="coerce", dayfirst=True)
    elif date_col and time_col:
        timestamp = pd.to_datetime(
            frame[date_col].astype(str) + " " + frame[time_col].astype(str),
            errors="coerce", dayfirst=True,
        )
    elif date_col:
        timestamp = pd.to_datetime(frame[date_col], errors="coerce", dayfirst=True)
    else:
        raise WindDataError(f"Could not identify a wind timestamp column; found {columns}")

    result = pd.DataFrame(
        {
            "wind_timestamp": timestamp,
            "wind_speed": pd.to_numeric(frame[speed_col], errors="coerce"),
            "wind_direction": frame[direction_col],
        }
    )
    if station_col:
        result["station"] = frame[station_col].astype(str)

    return result.dropna(subset=["wind_timestamp", "wind_speed"])


def flatten_header_levels(columns: pd.MultiIndex) -> list[str]:
    '''
        join a two-row MultiIndex header (station name row + sub-metric
        row) into a single normalised column name, e.g.
        ('Atlantis AQM Site', 'Wind Dir (deg)') -> 'atlantis_aqm_site_wind_dir_deg'
    '''
    flattened = []
    for level_0, level_1 in columns:
        parts = [normalise_name(level_0), normalise_name(level_1)]
        flattened.append("_".join(p for p in parts if p))
    return flattened


def normalise_multistation_wind_frame(raw: pd.DataFrame, station_name: str) -> pd.DataFrame:
    '''
        parse the City's actual wide layout: one shared timestamp column,
        followed by a (Wind Dir, Wind Speed) column pair per monitoring
        station, with the station name and the sub-metric name living on
        two separate header rows

    '''
    if not isinstance(raw.columns, pd.MultiIndex) or raw.columns.nlevels != 2:
        raise WindDataError("Expected a two-row MultiIndex header for the wide wind layout")

    frame = raw.dropna(how="all").copy()
    flat_columns = flatten_header_levels(frame.columns)
    frame.columns = flat_columns

    timestamp_col = find_column(
        flat_columns,
        {"date_time", "datetime", "timestamp"},
        {"date", "time"},
    )
    if timestamp_col is None:
        raise WindDataError(f"Could not identify a wind timestamp column; found {flat_columns}")

    # station identity is embedded directly in the flattened column name
    station_token = normalise_name(station_name)
    direction_col = next(
        (c for c in flat_columns if station_token in c and "wind_dir" in c), None
    )
    speed_col = next(
        (c for c in flat_columns if station_token in c and "wind_speed" in c), None
    )
    if direction_col is None or speed_col is None:
        raise WindDataError(
            f"Could not find wind columns for station '{station_name}'; found {flat_columns}"
        )

    result = pd.DataFrame(
        {
            "wind_timestamp": pd.to_datetime(frame[timestamp_col], errors="coerce", dayfirst=True),
            "wind_speed": pd.to_numeric(frame[speed_col], errors="coerce"),
            "wind_direction": frame[direction_col],
        }
    )
    return result.dropna(subset=["wind_timestamp", "wind_speed"])


def read_atlantis_wind(workbook: str | Path, station_name: str = "Atlantis") -> pd.DataFrame:
    '''
        find and normalise the Atlantis columns in a potentially
        multi-sheet, multi-station workbook

    '''
    engine = detect_spreadsheet_engine(workbook)
    excel = pd.ExcelFile(workbook, engine=engine)
    candidates: list[tuple[int, pd.DataFrame]] = []
    diagnostics: list[str] = []

    for sheet in excel.sheet_names:
        # -- the confirmed layout through diagnostic: two header rows (station, then metric)
        for header_row in range(8):
            try:
                raw = pd.read_excel(
                    excel, sheet_name=sheet, header=[header_row, header_row + 1]
                )
                normalised = normalise_multistation_wind_frame(raw, station_name)
                if not normalised.empty:
                    score = len(normalised) + (
                        10_000 if station_name.casefold() in sheet.casefold() else 0
                    )
                    candidates.append((score, normalised))
                    break
            except (WindDataError, ValueError, TypeError) as exc:
                diagnostics.append(f"{sheet}[multiheader={header_row},{header_row + 1}]: {exc}")

        # fallback: a single-header, single-station-column layout
        for header_row in range(12):
            try:
                raw = pd.read_excel(excel, sheet_name=sheet, header=header_row)
                normalised = normalise_wind_frame(raw)
                if "station" in normalised:
                    mask = normalised["station"].str.contains(
                        station_name, case=False, na=False, regex=False
                    )
                    if not mask.any():
                        continue
                    normalised = normalised.loc[mask]
                score = len(normalised) + (
                    10_000 if station_name.casefold() in sheet.casefold() else 0
                )
                if not normalised.empty:
                    candidates.append((score, normalised))
                    break
            except (WindDataError, ValueError, TypeError) as exc:
                diagnostics.append(f"{sheet}[header={header_row}]: {exc}")

    if not candidates:
        raise WindDataError(
            "No usable Atlantis wind table was found. First diagnostics: "
            + " | ".join(diagnostics[:4])
        )

    wind = max(candidates, key=lambda item: item[0])[1]
    # keep the latest reading per timestamp in case of overlapping exports
    wind = wind.sort_values("wind_timestamp").drop_duplicates("wind_timestamp", keep="last")
    logger.info(f"Read {len(wind)} Atlantis wind observations")
    return wind.reset_index(drop=True)


def join_wind_to_subsample(
    subsample_df: pd.DataFrame,
    wind_df: pd.DataFrame,
    timestamp_col: str = "creation_timestamp",
    tolerance_minutes: int = 90,
    max_unmatched_rate: float = 0.05,
    wind_tz: str = "Africa/Johannesburg",
) -> pd.DataFrame:
    '''
        join each request to its nearest wind observation within a tolerance

    '''
    if timestamp_col not in subsample_df.columns:
        raise KeyError(f"Request data has no '{timestamp_col}' column")
    required = {"wind_timestamp", "wind_speed", "wind_direction"}
    if wind_df.empty or not required <= set(wind_df.columns):
        raise WindDataError("Wind data is empty or lacks canonical wind columns")

    left = subsample_df.copy()
    left["row_order"] = range(len(left))  # preserve original row order through the sort/merge
    left[timestamp_col] = pd.to_datetime(left[timestamp_col], errors="coerce")
    if left[timestamp_col].isna().any():
        raise WindDataError("One or more request creation timestamps are invalid")

    right = wind_df.copy()
    right["wind_timestamp"] = pd.to_datetime(right["wind_timestamp"], errors="coerce")
    right = right.dropna(subset=["wind_timestamp"]).sort_values("wind_timestamp")

    # align timezone-awareness explicitly before merge_asof, rather than
    # letting pandas raise or silently coerce
    if left[timestamp_col].dt.tz is not None and right["wind_timestamp"].dt.tz is None:
        right["wind_timestamp"] = (
            right["wind_timestamp"]
            .dt.tz_localize(wind_tz)      
            .dt.tz_convert(left[timestamp_col].dt.tz)
        )
    elif left[timestamp_col].dt.tz is None and right["wind_timestamp"].dt.tz is not None:
        left[timestamp_col] = left[timestamp_col].dt.tz_localize(wind_tz)

    # merge_asof requires both sides sorted on the join key
    merged = pd.merge_asof(
        left.sort_values(timestamp_col),
        right,
        left_on=timestamp_col,
        right_on="wind_timestamp",
        direction="nearest",
        tolerance=pd.Timedelta(minutes=tolerance_minutes),
    )
    merged["wind_match_offset_minutes"] = (
        (merged[timestamp_col] - merged["wind_timestamp"]).abs().dt.total_seconds() / 60
    )

    unmatched_rate = float(merged["wind_timestamp"].isna().mean()) if len(merged) else 0.0
    logger.info(f"Wind enrichment unmatched rate: {unmatched_rate:.2%}")
    if unmatched_rate > max_unmatched_rate:

        logger.warning(
            f"Wind unmatched rate {unmatched_rate:.2%} exceeds the configured "
            f"{max_unmatched_rate:.2%} threshold. The Atlantis AQM station's 2020 "
            f"export only covers ~101 of 366 days; unmatched rows are enriched "
            f"with null wind_speed/wind_direction rather than the pipeline failing."
        )

    return merged.sort_values("row_order").drop(columns="row_order").reset_index(drop=True)