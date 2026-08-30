'''
    task 5 sub-task 1
        - selects requests near the centroid of official Atlantis suburb.
'''

import json
from pathlib import Path
import geopandas as gpd
import pandas as pd
import requests

from tenacity import (
    retry, 
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.settings import logger

@retry(
    stop = stop_after_attempt(4),
    wait = wait_exponential_jitter(initial=1, max=15),
    retry = retry_if_exception_type(requests.RequestException),
    reraise = True,
)

def download_official_suburbs(url : str, name_column: str) -> dict:
    '''
        download the official city suburb polygons as GeoJSON
    '''

    params = {
        "where":"1=1",             # very suburb record
        "outFields":name_column,   # return suburb-name record
        "returnGeometry":"true",   # each suburb polygon
        "outSR":"4326",            # coords in WGS 84
        "f":"geojson"              
    }

    response = requests.get(
        url, 
        params = params,
        timeout = 45
    )
    response.raise_for_status()

    payload = response.json()

    if not payload.get("features"):
        raise RuntimeError("official suburb service returned no features...")
    return payload

def load_official_suburbs(
        query_url: str,
        cache_path: str | Path,
        name_column: str = "OFC_SBRB_NAME",
) -> gpd.GeoDataFrame:
    
    '''
        load official sbrb polygons - use cache is download fails
    '''

    cache_path = Path(cache_path)

    try:
        payload = download_official_suburbs(query_url, name_column)

        cache_path.parent.mkdir(parents = True, exist_ok = True)
        cache_path.write_text(json.dumps(payload), encoding = "utf-8")

        logger.info(f"downloaded and cached {len(payload["features"])} official suburbs")

    except (requests.RequestException, RuntimeError, ValueError) as e:
        if not cache_path.exists():
            raise RuntimeError(
                "the official sbrb layer is unavailable and not local cache found"
            ) from e
        
        logger.warning(f"official sbrb download failed using {cache_path}: {e}")
    
    suburbs = gpd.read_file(cache_path)

    if suburbs.empty:
        raise RuntimeError("no polygons found in the official suburb cache")
    return suburbs

def get_suburb_centroid(
        suburbs: gpd.GeoDataFrame, 
        suburb_name: str,
        name_column: str,
        projected_crs: str,
) -> gpd.GeoSeries:
    
    '''
        calculate selected sbrb's centroid in a metric crs
    '''
    if name_column not in suburbs.columns:
        raise KeyError(
            f"Official suburb layer has no '{name_column}' field"
        )
    
    # normalize to a rest frame - e.g. Robinvale & ROBINVALE is the same thing, also whitespaces

    match = suburbs[
        suburbs[name_column].astype(str).str.strip().str.casefold() == suburb_name.strip().casefold()
    ]

    if match.empty:
        raise ValueError(
            f"Suburb '{suburb_name}' was not found in the official layer"
        )
    
    # reprojecting coords (lat/lon) to crs measured in meters for numeric calcs

    projected = match.to_crs(projected_crs)

    geometry = projected.geometry.union_all()
    centroid = geometry.centroid

    return gpd.GeoSeries([centroid], crs = projected_crs)

def filter_requests_near_suburb(
    sr_df: pd.DataFrame,
    centroid: gpd.GeoSeries,
    lat_col: str,
    lon_col: str,
    radius_metres: float,
) -> pd.DataFrame:
    
    '''
        selects requests within a specified distance of the suburb centroid
    '''

    missing = {lat_col, lon_col} - set(sr_df.columns)

    if missing:
        raise KeyError(
            f"service-request is missing columns: {sorted(missing)}"
        )
    working = sr_df.copy()

    # invalid coords handling

    working[lat_col] = pd.to_numeric(
        working[lat_col],
        errors = "coerce"
    )

    working[lon_col] = pd.to_numeric(
        working[lon_col],
        errors = "coerce"
    )

    valid = (
        working[lat_col].between(-90, 90) & working[lon_col].between(-180, 180)
    )

    points = gpd.GeoDataFrame(
        working.loc[valid],
        geometry = gpd.points_from_xy(working.loc[valid, lon_col], working.loc[valid, lat_col]),
        crs = "EPSG:4326"
    )

    # convert the points to the same metric crs as the centroid for consistent units

    points = points.to_crs(centroid.crs)

    distances = points.geometry.distance(centroid.iloc[0])
    selected = points.loc[distances <= radius_metres]

    # geometry was only required for filtering
    
    selected = selected.drop(columns="geometry")

    logger.info(
        f"Selected {len(selected)} of {len(sr_df)} requests within "
        f"{radius_metres:.0f} m of the selected suburb centroid"
    )

    return pd.DataFrame(selected)