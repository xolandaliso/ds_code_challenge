import json
from unittest.mock import MagicMock, patch

import pytest

from src.extract import extract_hex_resolution8, extract_resolution8_via_s3_select

FEATURES = [
    {
        "type": "Feature",
        "properties": {"index": "88ad3615ebfffff", "resolution": 8},
        "geometry": {"type": "Polygon", "coordinates": []},
    },
    {
        "type": "Feature",
        "properties": {"index": "88ad3615ecfffff", "resolution": 8},
        "geometry": {"type": "Polygon", "coordinates": []},
    },
]


@patch("src.extract.get_s3_client")
def test_s3_select_parses_record_events(mock_get_client):
    payload = "".join(json.dumps(feature) + "\n" for feature in FEATURES).encode()
    midpoint = len(payload) // 2
    mock_s3 = MagicMock()
    mock_s3.select_object_content.return_value = {
        "Payload": [
            {"Records": {"Payload": payload[:midpoint]}},
            {"Progress": {}},
            {"Records": {"Payload": payload[midpoint:]}},
            {"End": {}},
        ]
    }
    mock_get_client.return_value = mock_s3

    result = extract_resolution8_via_s3_select("bucket", "mixed.geojson", 8)

    assert result == FEATURES
    request = mock_s3.select_object_content.call_args.kwargs
    assert request["Bucket"] == "bucket"
    assert request["Key"] == "mixed.geojson"
    assert "properties.resolution = 8" in request["Expression"]
    assert request["InputSerialization"] == {"JSON": {"Type": "DOCUMENT"}}


@patch("src.extract.extract_resolution8_via_s3_select")
def test_entrypoint_returns_s3_select_records(mock_select):
    mock_select.return_value = FEATURES
    assert extract_hex_resolution8() == FEATURES


@patch("src.extract.extract_resolution8_via_s3_select")
def test_entrypoint_fails_loudly_when_s3_select_returns_nothing(mock_select):
    mock_select.return_value = []
    with pytest.raises(RuntimeError, match="no records"):
        extract_hex_resolution8()


@patch("src.extract.extract_resolution8_via_s3_select")
def test_entrypoint_fails_loudly_when_s3_select_errors(mock_select):
    mock_select.side_effect = OSError("network unavailable")
    with pytest.raises(RuntimeError, match="S3 Select"):
        extract_hex_resolution8()