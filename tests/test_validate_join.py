import pandas as pd
import pytest

from src.validate_join import validate_join_against_reference


def test_exact_reference_match():
    generated = pd.DataFrame({"id": [1, 2], "h3": ["abc", "0"]})
    reference = pd.DataFrame({"id": [1, 2], "h3": ["abc", "0"]})

    result = validate_join_against_reference(generated, reference, "h3", ["id"])

    assert result.is_exact_match
    assert result.matched_rows == 2


def test_h3_mismatch_is_counted():
    generated = pd.DataFrame({"id": [1], "h3": ["abc"]})
    reference = pd.DataFrame({"id": [1], "h3": ["xyz"]})

    result = validate_join_against_reference(generated, reference, "h3", ["id"])

    assert not result.is_exact_match
    assert result.mismatched_rows == 1


def test_reordered_rows_are_rejected_before_h3_comparison():
    generated = pd.DataFrame({"id": [1, 2], "h3": ["abc", "def"]})
    reference = pd.DataFrame({"id": [2, 1], "h3": ["def", "abc"]})

    with pytest.raises(ValueError, match="not in the same order"):
        validate_join_against_reference(generated, reference, "h3", ["id"])


def test_different_row_counts_are_rejected():
    generated = pd.DataFrame({"id": [1], "h3": ["abc"]})
    reference = pd.DataFrame({"id": [1, 2], "h3": ["abc", "def"]})

    with pytest.raises(ValueError, match="Row count differs"):
        validate_join_against_reference(generated, reference, "h3", ["id"])


def test_missing_configured_validation_key_is_rejected():
    generated = pd.DataFrame({"h3": ["abc"]})
    reference = pd.DataFrame({"h3": ["abc"]})

    with pytest.raises(KeyError, match="id"):
        validate_join_against_reference(generated, reference, "h3", ["id"])
