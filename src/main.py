'''
    - pipeline entrypoint for the DE challenge tasks

'''
import io
import pandas as pd
import json, gzip, yaml
from pathlib import Path
from src.utils import load_yaml, timed, read_gzip_csv_from_s3

# task 1
from src.extract import extract_hex_resolution8
from src.validate_extraction import validate_extraction, load_reference_index_set
from src.schema_conformance import score_features

# task 2
from src.transform_join import join_service_requests_to_hex
from src.validate_join import validate_join_against_reference

# task 5
from src.subsample_atlantis import (
    load_official_suburbs,
    get_suburb_centroid,
    filter_requests_near_suburb,
)
from src.augment_wind import fetch_wind_workbook, read_atlantis_wind, join_wind_to_subsample
from src.anonymize import anonymise_subsample

from src.settings import Settings, get_s3_client, logger


def run_task_extraction() -> list[dict]:
    logger.info("------- 1st task - res8 extraction and validation ---------")
    with timed("Task 1"):
        features = extract_hex_resolution8()
        schema = load_yaml("config/hex_schema.yml")
        conformance = score_features(features, schema)

        logger.info(conformance.summary(schema.get("score_bands")))
        reference_index_set = load_reference_index_set()

        validation = validate_extraction(features, reference_index_set)
        logger.info(validation.summary())

        out_dir = Path(Settings.OUTPUT_DIR)
        out_dir.mkdir(parents = True, exist_ok = True)

        out_path = out_dir / "task1_extracted_features.json"
        with out_path.open("w") as handle:
            json.dump(features, handle)

    return features

def run_task_srequests(reference_df: pd.DataFrame | None = None) -> tuple[pd.DataFrame, object]:
    logger.info("------- 2nd task - service request mapping ---------")
    with timed("Task 2"):
        config = load_yaml("config/join_config.yml")
        sr_df = read_gzip_csv_from_s3(Settings.SR_KEY)
        joined_df, report = join_service_requests_to_hex(sr_df, config)

        if reference_df is None:
            reference_df = read_gzip_csv_from_s3(Settings.SR_HEX_KEY)
        
        validation = validate_join_against_reference(
            joined_df,
            reference_df,
            config["columns"]["output_index"],
            config["columns"].get("validation_key_columns")
        )
        logger.info(validation.summary())

        if not validation.is_exact_match:
            raise RuntimeError("Task 2 output does not match the reference exactly...")
        
        out_dir = Path(Settings.OUTPUT_DIR)
        out_dir.mkdir(parents = True, exist_ok = True)

        joined_df.to_csv(out_dir / "sr_hex_joined.csv", index = False)

        return joined_df, report


def run_task_subsample_and_anonymise(sr_hex_df: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    
    logger.info("------- 5th task - suburb subsample, wind join, anonymisation ---------")
    with timed("Task 5"):
        config = load_yaml("config/task5.yml")
        out_dir = Path(Settings.OUTPUT_DIR)
        out_dir.mkdir(parents = True, exist_ok = True)

        # --- 5.1: spatial subsample around the suburb centroid ---
        if sr_hex_df is None:
            sr_hex_df = read_gzip_csv_from_s3(Settings.SR_HEX_KEY)

        suburb_cfg = config["suburb"]
        suburbs = load_official_suburbs(
            query_url = suburb_cfg["query_url"],
            cache_path = suburb_cfg["cache_path"],
            name_column = suburb_cfg["name_column"],
        )
        centroid = get_suburb_centroid(
            suburbs,
            suburb_name = suburb_cfg["name"],
            name_column = suburb_cfg["name_column"],
            projected_crs = suburb_cfg["projected_crs"],
        )
        subsample_df = filter_requests_near_suburb(
            sr_hex_df,
            centroid,
            lat_col = config["columns"]["latitude"],
            lon_col = config["columns"]["longitude"],
            radius_metres = suburb_cfg["radius_metres"],
        )
        subsample_df.to_csv(out_dir / "task5_1_subsample.csv", index = False)

        # --- 5.2: augment with Atlantis wind data ---
        wind_cfg = config["wind"]
        workbook_path = fetch_wind_workbook(
            urls = wind_cfg["urls"],
            cache_path = wind_cfg["cache_path"],
        )
        wind_df = read_atlantis_wind(workbook_path, station_name = wind_cfg.get("station_name", "Atlantis"))
        logger.warning("***----added this for diagnostic---***")
        request_timestamps = pd.to_datetime(subsample_df["creation_timestamp"], errors="coerce")
        print(request_timestamps.dt.year.value_counts().sort_index())
        print(wind_df["wind_timestamp"].min(), wind_df["wind_timestamp"].max())
        print(wind_df["wind_timestamp"].dt.date.nunique(), "distinct days covered")
        logger.warning("***---- diagnostic ends here---***")
        augmented_df = join_wind_to_subsample(
            subsample_df,
            wind_df,
            timestamp_col = config["columns"]["request_timestamp"],
            tolerance_minutes = wind_cfg.get("match_tolerance_minutes", 90),
            max_unmatched_rate = wind_cfg.get("max_unmatched_rate", 0.05),
        )
        augmented_df.to_csv(out_dir / "task5_2_augmented.csv", index = False)


        # --- 5.3: anonymise, isolating identifiers for manual review ---
        anonymise_cfg = config.get("anonymisation", {})
        anonymised_df, manual_review_df = anonymise_subsample(
            augmented_df,
            lat_col = config["columns"]["latitude"],
            lon_col = config["columns"]["longitude"],
            timestamp_columns = config["columns"]["timestamp_columns"],
            hex_col = config["columns"]["h3_index"],
            direct_identifiers = config["columns"]["direct_identifiers"],
            drop_columns = config["columns"]["drop_columns"],
            time_bucket_hours = anonymise_cfg.get("time_bucket_hours", 6),
        )
        anonymised_df.to_csv(out_dir / "task5_3_anonymised.csv", index = False)

        # manual review table contains direct identifiers - keep it out of
        # the general OUTPUT_DIR and in a clearly-labelled restricted path
        review_dir = Path(Settings.OUTPUT_DIR) / "restricted_manual_review"
        review_dir.mkdir(parents = True, exist_ok = True)
        manual_review_df.to_csv(review_dir / "task5_3_manual_review.csv", index = False)

        logger.info(
            f"Task 5 complete: {len(anonymised_df)} anonymised rows, {len(manual_review_df)} rows flagged for manual review"
        )

    return anonymised_df, manual_review_df


if __name__ == "__main__":
    run_task_extraction()
    sr_hex_ref = read_gzip_csv_from_s3(Settings.SR_HEX_KEY)
    run_task_srequests(reference_df = sr_hex_ref)
    run_task_subsample_and_anonymise(sr_hex_df = sr_hex_ref)
    logger.info('pipeline finished - check outputs/ and logs/')