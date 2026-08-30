from src.validate_extraction import validate_extraction


def _feature(index: str) -> dict:
    return {"properties": {"index": index}}


def test_exact_extraction_matches_reference():
    result = validate_extraction([_feature("a"), _feature("b")], {"a", "b"})

    assert result.is_exact_match
    assert result.reference_count == 2
    assert result.extracted_count == 2
    assert result.matched_count == 2


def test_missing_and_unexpected_indexes_are_reported():
    result = validate_extraction(
        [_feature("a"), _feature("unexpected")], {"a", "missing"}
    )

    assert not result.is_exact_match
    assert result.missing_from_extraction == {"missing"}
    assert result.unexpected_in_extraction == {"unexpected"}
