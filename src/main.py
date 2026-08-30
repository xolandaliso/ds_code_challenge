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
    

if __name__ == "__main__":
    run_task_extraction()
    sr_hex_ref = read_gzip_csv_from_s3(Settings.SR_HEX_KEY)
    run_task_srequests(reference_df = sr_hex_ref)
    logger.info('pipeline finished - check outputs/ and logs/')