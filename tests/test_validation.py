from datetime import UTC, datetime

import polars as pl

from demandsense.data.validation import demand_segment, validate_canonical


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
