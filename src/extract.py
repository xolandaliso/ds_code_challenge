'''
task 1 — data extraction.

    - use S3 Select to pull the resolution-8 records out of
    city-hex-polygons-8-10.geojson (also contains res 8, 9 & 10), without downloading the whole object. 

    - validate (implemented in validate_extraction.py) against city-hex-polygons-8.geojson (this only has res 8 data)
'''

import time
import json
from typing import Any
from contextlib import contextmanager
from src.settings import Settings, get_s3_client, logger

@contextmanager
def timed(label: str):
    '''
        purpose: simple context manager for measuring & logging execution time.
        usage:
            with timed("some operation"):
                do_something()
    '''
    start = time.perf_counter()
    status = "success"

    try:
        yield
    except Exception:
        status = "failed"
        raise  
    finally:
        elapsed = time.perf_counter() - start
        logger.info(f"{status}: {label} took {elapsed:.3f}s")

def extract_resolution8_via_s3_select(
        bucket: str = Settings.S3_BUCKET,
        key: str = Settings.HEX_RES8_10_KEY,
        resolution: int = 8,
    ):
    '''
        - server-side filtering via S3 select. 
        - returns : 
            - a list of GeoJSON feature dicts with the given resolution.
    '''
    s3 = get_s3_client()

    expression = (
        "SELECT f.* FROM S3Object[*].features[*] f "
        f"WHERE f.properties.resolution = {resolution}"
    )

    with timed("S3 Select query"):
        response = s3.select_object_content(
            Bucket = bucket,
            Key = key,
            ExpressionType = "SQL",
            Expression = expression,
            InputSerialization = {"JSON": {"Type": "DOCUMENT"}},
            OutputSerialization = {"JSON": {"RecordDelimiter": "\n"}},
        )

        records: list[dict[str, Any]] = []
        buffer = ""
        for event in response["Payload"]:
            if "Records" in event:
                buffer += event["Records"]["Payload"].decode("utf-8")
        for line in buffer.splitlines():
            if line.strip():
                records.append(json.loads(line))

    logger.info(f"S3 Select returned {len(records)} resolution-{resolution} features")
    return records

def extract_hex_resolution8(
    bucket: str = Settings.S3_BUCKET,
    key: str = Settings.HEX_RES8_10_KEY,
    resolution: int = 8,
) -> list[dict[str, Any]]:
  
    try:
        features = extract_resolution8_via_s3_select(bucket, key, resolution)
        if features:
            return features
        logger.warning("s3 select returned no records....")

    except Exception as exc:  
        logger.warning(f"there was an error using s3 select - check your connection and debug : {exc}")

if __name__ == "__main__":
    features = extract_hex_resolution8()
    print(f"extracted {len(features)} res-8 features.")

