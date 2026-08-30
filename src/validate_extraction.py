'''
    task 1 validation — data extraction.

    - validate the extracted res-8 records
      against the reference city-hex-polygons-8.geojson (this only has res 8 data)

    - this does apples-to-apples comparison.
'''

import time
import json
from typing import Any
from dataclasses import dataclass
from src.extract import timed, extract_hex_resolution8
from src.settings import Settings, get_s3_client, logger


@dataclass
class ExtractionValidation:
    reference_count : int
    extracted_count : int
    matched_count : int
    missing_from_extraction : set[str]   # in the reference, not in the extraction
    unexpected_in_extraction : set[str]  # in the extraction but not in the reference

    @property
    def is_exact_match(self) -> bool:
        return (
          not self.missing_from_extraction and
          not self.unexpected_in_extraction
        )
    
    def summary(self) -> str:
        lines = [
            f"Ground truth records : {self.reference_count}",
            f"Extracted records    : {self.extracted_count}",
            f"Matched records      : {self.matched_count}",
            f"Missing from extraction : {len(self.missing_from_extraction)}",
            f"Unexpected in extraction : {len(self.unexpected_in_extraction)}",
            f"Exact match : {self.is_exact_match}"
        ]

        return "\n".join(lines)
    
def load_reference_index_set(bucket: str = Settings.S3_BUCKET, key: str = Settings.HEX_RES8_KEY) -> set[str]:
    '''
        load the ref hex res-8 data from S3 and return a set of unique indices.
    '''
    s3 = get_s3_client()
    with timed("Loading reference data from S3"):
        response = s3.get_object(Bucket = bucket, Key = key)
        content = response['Body'].read().decode('utf-8')
        geojson_data = json.loads(content)
    
    index_set = {feature['properties']['index'] for feature in geojson_data['features']}
    return index_set

def validate_extraction(extracted_features: list[dict[str, Any]], reference_index_set: set[str]) -> ExtractionValidation:
    '''
        validate the extracted features against the reference index set.
    '''
    extracted_indices = {feature['properties']['index'] for feature in extracted_features}

    missing_from_extraction = reference_index_set - extracted_indices
    unexpected_in_extraction = extracted_indices - reference_index_set
    matched_count = len(reference_index_set & extracted_indices)

    result =  ExtractionValidation(
        reference_count=len(reference_index_set),
        extracted_count=len(extracted_indices),
        matched_count=matched_count,
        missing_from_extraction=missing_from_extraction,
        unexpected_in_extraction=unexpected_in_extraction
    )

    logger.info(f"validation summary:\n {result.summary()}" )
    return result

if __name__ == "__main__":
    reference_indices = load_reference_index_set()

    # extract res-8 feats
    extracted_features = extract_hex_resolution8()

    # validate extraction
    validation_result = validate_extraction(extracted_features, reference_indices)

    #logger.info(f"validation result \n: {validation_result.summary()}") -- redundant
