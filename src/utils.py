import pandas as pd
from typing import Any
import time, yaml, gzip, io
from contextlib import contextmanager
from src.settings import logger, Settings, get_s3_client


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

def load_yaml(path: str) -> dict[str, Any]:
    '''
        load the expected schema from a yaml file.
    '''
    with open(path, 'r') as f:
        schema = yaml.safe_load(f)
    return schema

def read_gzip_csv_from_s3(key: str) -> pd.DataFrame:
    obj = get_s3_client().get_object(Bucket=Settings.S3_BUCKET, Key=key)
    raw = gzip.decompress(obj["Body"].read())
    return pd.read_csv(io.BytesIO(raw))

