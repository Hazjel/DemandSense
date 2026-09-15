from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import polars as pl

REQUIRED_COLUMNS = {
    "date",
    "store_id",
    "sku_id",
    "category",
    "quantity_sold",
    "source",
    "ingested_at",
}

MANIFEST_COLUMNS = {
    "dataset_version",
    "store_id",
    "sku_id",
    "zero_sales_ratio",
    "history_days",
    "segment",
    "selection_seed",
    "cohort_role",
    "included",
    "exclusion_reason",
    "eligible",
    "reference_end_date",
    "eligibility_cutoff_date",
    "eligibility_history_days",
    "eligibility_total_sales",
}
MANIFEST_NON_NULL_COLUMNS = MANIFEST_COLUMNS - {"exclusion_reason"}
VALID_SEGMENTS = {"fast", "medium", "intermittent"}


@dataclass(frozen=True)
class ValidationReport:
    status: str
    row_count: int
    series_count: int
    min_date: str | None
    max_date: str | None
    duplicate_keys: int
    negative_quantity_rows: int
    null_required_rows: int
    missing_columns: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ManifestValidationReport:
    status: str
    row_count: int
    duplicate_keys: int
    null_required_rows: int
    invalid_segment_rows: int
    invalid_history_rows: int
    missing_columns: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_canonical(frame: pl.DataFrame) -> ValidationReport:
    missing = sorted(REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        return ValidationReport(
            status="failed",
            row_count=frame.height,
            series_count=0,
            min_date=None,
            max_date=None,
            duplicate_keys=0,
            negative_quantity_rows=0,
            null_required_rows=0,
            missing_columns=missing,
        )

    duplicate_keys = frame.select(
        pl.struct(["date", "store_id", "sku_id"]).is_duplicated().sum()
    ).item()
    negative_rows = frame.select((pl.col("quantity_sold") < 0).sum()).item()
    null_required = frame.select(
        pl.any_horizontal([pl.col(column).is_null() for column in REQUIRED_COLUMNS]).sum()
    ).item()
    dates = frame.select(
        pl.col("date").min().alias("min_date"),
        pl.col("date").max().alias("max_date"),
    ).row(0)
    series_count = frame.select(pl.struct(["store_id", "sku_id"]).n_unique()).item()

    passed = duplicate_keys == 0 and negative_rows == 0 and null_required == 0
    return ValidationReport(
        status="passed" if passed else "failed",
        row_count=frame.height,
        series_count=series_count,
        min_date=str(dates[0]) if dates[0] is not None else None,
        max_date=str(dates[1]) if dates[1] is not None else None,
        duplicate_keys=duplicate_keys,
        negative_quantity_rows=negative_rows,
        null_required_rows=null_required,
        missing_columns=[],
    )


def validate_series_manifest(frame: pl.DataFrame) -> ManifestValidationReport:
    missing = sorted(MANIFEST_COLUMNS.difference(frame.columns))
    if missing:
        return ManifestValidationReport(
            status="failed",
            row_count=frame.height,
            duplicate_keys=0,
            null_required_rows=0,
            invalid_segment_rows=0,
            invalid_history_rows=0,
            missing_columns=missing,
        )

    duplicate_keys = frame.select(
        pl.struct(["dataset_version", "store_id", "sku_id"]).is_duplicated().sum()
    ).item()
    null_required = frame.select(
        pl.any_horizontal(
            [pl.col(column).is_null() for column in MANIFEST_NON_NULL_COLUMNS]
        ).sum()
    ).item()
    invalid_segments = frame.select(
        (~pl.col("segment").is_in(sorted(VALID_SEGMENTS))).sum()
    ).item()
    invalid_history = frame.select((pl.col("history_days") <= 0).sum()).item()
    passed = all(
        value == 0
        for value in (
            duplicate_keys,
            null_required,
            invalid_segments,
            invalid_history,
        )
    )
    return ManifestValidationReport(
        status="passed" if passed else "failed",
        row_count=frame.height,
        duplicate_keys=duplicate_keys,
        null_required_rows=null_required,
        invalid_segment_rows=invalid_segments,
        invalid_history_rows=invalid_history,
        missing_columns=[],
    )


def demand_segment(
    zero_sales_ratio: float,
    fast_max_zero_ratio: float = 0.20,
    intermittent_min_zero_ratio: float = 0.60,
) -> str:
    if zero_sales_ratio < fast_max_zero_ratio:
        return "fast"
    if zero_sales_ratio > intermittent_min_zero_ratio:
        return "intermittent"
    return "medium"
