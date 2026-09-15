from datetime import UTC, datetime

import polars as pl

from demandsense.data.validation import (
    demand_segment,
    validate_canonical,
    validate_series_manifest,
)


def _valid_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": [datetime(2026, 1, 1).date(), datetime(2026, 1, 2).date()],
            "store_id": ["CA_1", "CA_1"],
            "sku_id": ["ITEM_1", "ITEM_1"],
            "category": ["FOODS", "FOODS"],
            "quantity_sold": [1.0, 0.0],
            "source": ["fixture", "fixture"],
            "ingested_at": [datetime.now(UTC), datetime.now(UTC)],
        }
    )


def test_valid_canonical_frame_passes() -> None:
    report = validate_canonical(_valid_frame())

    assert report.status == "passed"
    assert report.row_count == 2
    assert report.series_count == 1


def test_duplicate_key_fails() -> None:
    frame = pl.concat([_valid_frame(), _valid_frame().head(1)])
    report = validate_canonical(frame)

    assert report.status == "failed"
    assert report.duplicate_keys == 2


def test_demand_segment_boundaries() -> None:
    assert demand_segment(0.19) == "fast"
    assert demand_segment(0.20) == "medium"
    assert demand_segment(0.60) == "medium"
    assert demand_segment(0.61) == "intermittent"


def _valid_manifest() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dataset_version": ["m5-smoke-test"],
            "store_id": ["CA_1"],
            "sku_id": ["ITEM_1"],
            "zero_sales_ratio": [0.5],
            "history_days": [1941],
            "segment": ["medium"],
            "selection_seed": [42],
            "cohort_role": ["smoke"],
            "included": [True],
            "exclusion_reason": [None],
            "eligible": [True],
            "reference_end_date": [datetime(2026, 4, 24).date()],
            "eligibility_cutoff_date": [datetime(2026, 1, 31).date()],
            "eligibility_history_days": [112],
            "eligibility_total_sales": [42.0],
        }
    )


def test_valid_series_manifest_passes() -> None:
    report = validate_series_manifest(_valid_manifest())

    assert report.status == "passed"
    assert report.row_count == 1


def test_manifest_without_dataset_version_fails() -> None:
    report = validate_series_manifest(_valid_manifest().drop("dataset_version"))

    assert report.status == "failed"
    assert report.missing_columns == ["dataset_version"]
