from src.schema_conformance import score_features
from src.utils import load_yaml

SCHEMA = load_yaml("config/hex_schema.yml")


def _feature(**property_overrides) -> dict:
    properties = {
        "index": "88ad3615ebfffff",
        "resolution": 8,
        "centroid_lat": -33.9,
        "centroid_lon": 18.4,
    }
    properties.update(property_overrides)
    return {
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[18.4, -33.9], [18.5, -33.9], [18.5, -34.0], [18.4, -33.9]]
            ],
        },
    }


def test_conforming_feature_scores_one():
    result = score_features([_feature()], SCHEMA)
    assert result.mean_score == 1.0
    assert result.pass_count == 1
    assert result.band(SCHEMA["score_bands"]) == "pass"


def test_wrong_resolution_reduces_score_and_records_reason():
    result = score_features([_feature(resolution=9)], SCHEMA)
    assert 0 < result.mean_score < 1
    assert result.violations["resolution: unexpected value"] == 1


def test_missing_index_and_invalid_geometry_are_penalised():
    feature = _feature()
    del feature["properties"]["index"]
    feature["geometry"]["coordinates"] = [[[18.4, -33.9]]]

    result = score_features([feature], SCHEMA)

    assert result.mean_score < 1
    assert result.violations["index: missing/null"] == 1
    assert result.violations["geometry: invalid/insufficient"] == 1


def test_empty_dataset_returns_zero_score():
    result = score_features([], SCHEMA)
    assert result.total_records == 0
    assert result.mean_score == 0
