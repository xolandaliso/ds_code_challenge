'''
    -validation for the task 2 service-request H3 join.
'''

import pandas as pd
from dataclasses import dataclass


@dataclass(frozen=True)
class JoinValidation:
    total_rows: int
    matched_rows: int
    mismatched_rows: int

    @property
    def is_exact_match(self) -> bool:
        return self.mismatched_rows == 0

    def summary(self) -> str:
        return (
            f"Reference rows     : {self.total_rows}\n"
            f"Matching H3 rows  : {self.matched_rows}\n"
            f"Mismatched H3 rows: {self.mismatched_rows}\n"
            f"Exact match        : {self.is_exact_match}"
        )


def validate_join_against_reference(
    joined_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    index_col: str,
    key_columns: list[str] | None = None,
) -> JoinValidation:
    '''
        compare generated H3 values with the supplied ref row-for-row.
    '''

    if len(joined_df) != len(reference_df):
        raise ValueError(
            f"Row count differs from reference: generated={len(joined_df)}, "
            f"reference={len(reference_df)}"
        )
    for label, frame in (("generated", joined_df), ("reference", reference_df)):
        if index_col not in frame.columns:
            raise KeyError(f"{label} data has no '{index_col}' column")

    key_columns = key_columns or []
    common_keys = [
        column for column in key_columns
        if column in joined_df.columns and column in reference_df.columns
    ]
    if common_keys:
        left_keys = joined_df[common_keys].fillna("<NULL>").astype(str).reset_index(drop=True)
        right_keys = reference_df[common_keys].fillna("<NULL>").astype(str).reset_index(drop=True)
        if not left_keys.equals(right_keys):
            raise ValueError(
                "Reference rows are not in the same order as generated rows; "
                f"key check failed for {common_keys}"
            )

    generated = joined_df[index_col].fillna("<NULL>").astype(str).reset_index(drop=True)
    reference = reference_df[index_col].fillna("<NULL>").astype(str).reset_index(drop=True)
    matches = generated.eq(reference)
    matched_rows = int(matches.sum())
    return JoinValidation(
        total_rows=len(reference),
        matched_rows=matched_rows,
        mismatched_rows=len(reference) - matched_rows,
    )
