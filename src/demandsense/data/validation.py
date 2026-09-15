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
