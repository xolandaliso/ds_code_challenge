'''
    task 2 — initial data transformation.

        - joins each service request to a single H3 res-8 hexagon based on its
        coords (lat/long). requests with empty coords get the 0 index.

        - a request does count as a join failure if it has valid coordinates but:
            - h3 cannot resolve them to a cell, or
            - the resolved cell isn't present in the city's res-8 hex polygon set

        - logs record counts, timing, and the resulting join-failure rate, and raises
        if that rate exceeds join_error_threshold from config/join_config.yml.
'''
import io
import gzip
import h3, yaml, json
import pandas as pd
from src.utils import timed
from dataclasses import dataclass
from src.settings import Settings, get_s3_client, logger


class JoinThresholdExceededError(RuntimeError):
    '''
        - custom exception for join thresh exceeded
    '''
    pass

@dataclass
class JoinReport:
    total_rows: int
    null_geolocation_rows: int
    joined_rows: int
    failed_rows: int

    @property
    def eligible_rows(self) -> int:
        '''
            rows that had coords to try a join on
        '''

        return self.total_rows  - self.null_geolocation_rows
    @property
    def failure_rate(self) -> float:
        return self.failed_rows / self.eligible_rows if self.eligible_rows else 0.0

    
    def summary(self) -> str:
        lines = [
            f"Total rows              : {self.total_rows}\n"
            f"Null-geolocation rows    : {self.null_geolocation_rows} (assigned index '0')\n"
            f"Eligible rows (with lat/lon): {self.eligible_rows}\n"
            f"Successfully joined      : {self.joined_rows}\n"
            f"Failed to join           : {self.failed_rows}\n"
            f"Join failure rate        : {self.failure_rate:.4%}"
        ]

        return "\n".join(lines)
    

def load_join_config(path: str = "config/join_config.yml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
    
def load_valid_hex_set(bucket: str = Settings.S3_BUCKET, key: str = Settings.HEX_RES8_KEY) -> set[str]:
    '''
        set of h3 res-8 cells that are with COCT bounds
    '''

    s3 = get_s3_client()
    obj = s3.get_object(Bucket=bucket, Key=key)
    data = json.loads(obj["Body"].read())
    features = data.get("features", data)

    valid = set()
    for feature in features:
        props = feature.get("properties", {}) or {}
        idx = props.get("index") or props.get("h3_index")
        if idx:
            valid.add(str(idx))
    return valid

def join_service_requests_to_hex(sr_df: pd.DataFrame, config: dict, valid_hex_set: set[str]):

    '''
        main join logic
    '''

    config = config or load_join_config
    cols = config["columns"]

    lat_col, lon_col, out_col = cols['latitude'], cols['longitude'], cols['output_index']
    null_sentinel = config["h3"]["null_geolocations_index"]
    resolution = config["h3"]["resolution"]

    missing = {lat_col, lon_col} - set(sr_df.columns)

    if missing:
        raise KeyError(
            f"service-request data configured coordinate columns : {sorted(missing)}"
            f"available cols: {list(sr_df.columns)}"
        )
    
    if valid_hex_set is None:
        valid_hex_set = load_valid_hex_set()

    df = sr_df.copy()
    total_rows = len(df)

    row_has_coords = df[lat_col].notna() & df[lon_col].notna()
    numeric_lat, numeric_lon = pd.to_numeric(df[lat_col], errors="coerce"), pd.to_numeric(df[lon_col], errors="coerce")
    has_coords = row_has_coords
    null_geolocation_rows = int((~has_coords).sum())

    def resolve(lat, lon):

        try:
            if pd.isna(lat) or pd.isna(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return None
            return h3.latlng_to_cell(float(lat), float(lon), resolution)
        except Exception as e:
            logger.warning(f"there is an error here! : {e}")
            return None
        
    with timed("H3 resolution"):
        df[out_col] = pd.Series(null_sentinel, index = df.index, dtype = "object")

        eligible_index = df.index[has_coords]
        resolved = pd.Series(
            (resolve(numeric_lat.at[i], numeric_lon.at[i]) for i in eligible_index),
            index = eligible_index,
            dtype = "object"
        )
        
        df.loc[has_coords, out_col] = resolved

    logger.info(
        f"Processed {int(row_has_coords.sum())} rows containing coords"
    )
    '''
    
        - row fails if it had coords but res failed, or resolved
        to a cell that's not one of the COCT's actual res-8 cells.
    '''
    eligible = df.loc[has_coords]
    res_failed_mask = eligible[out_col].isna()   #resolution failed mask

    outside_coverage_mask = (eligible[out_col].notna() & ~eligible[out_col].isin(valid_hex_set))

    failed_mask = res_failed_mask | outside_coverage_mask
    failed_rows = int(failed_mask.sum())
    joined_rows = int(has_coords.sum()) - failed_rows

    '''
        - only replace values when H3 itself could not calculate an index.
         preserve valid H3 indices that fall outside the supplied City coverage.
    '''

    df.loc[eligible.index[res_failed_mask], out_col] = 'join_failed'
    outside_coverage_rows = int(outside_coverage_mask.sum())

    if outside_coverage_rows:
        logger.warning(f"retained {outside_coverage_rows} valid H3 indices outside City coverage")

        report = JoinReport(
            total_rows,
            null_geolocation_rows,
            joined_rows,
            failed_rows
        )
        logger.info(report.summary().replace("\n", " | "))
    
    threshold = config.get("join_error_threshold", 0.02)
    if report.failure_rate > threshold:
        raise JoinThresholdExceededError(
            f"Join failure rate {report.failure_rate:.4%} exceeds configured "
            f"threshold {threshold:.4%}. See config/join_config.yml for the "
            f"threshold and its rationale."
        )
    return df, report

if __name__ == "__main__":

    s3 = get_s3_client()
    obj = s3.get_object(Bucket = Settings.S3_BUCKET, Key = Settings.SR_KEY)
    raw = gzip.decompress(obj["Body"].read())
    sr_df = pd.read_csv(io.BytesIO(raw))

    joined_df, report = join_service_requests_to_hex(sr_df)
    print(report.summary())
    joined_df.to_csv(f"{Settings.OUTPUT_DIR}/sr_hex_joined.csv", index = False)