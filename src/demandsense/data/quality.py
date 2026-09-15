from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from demandsense.config import ProjectConfig


def validate_raw_m5(
    sales_path: Path,
    calendar_path: Path,
    prices_path: Path,
    store_id: str,
    day_columns: list[str],
) -> dict[str, Any]:
    sales = pl.scan_csv(sales_path).filter(pl.col("store_id") == store_id)
    sales_summary = sales.select(
        pl.len().alias("store_series_rows"),
        pl.col("id").n_unique().alias("unique_ids"),
        pl.col("item_id").n_unique().alias("unique_items"),
        pl.col("id").is_null().sum().alias("null_ids"),
    ).collect(engine="streaming").row(0, named=True)

    calendar = pl.scan_csv(calendar_path).select("d", "date", "wm_yr_wk")
    calendar_frame = calendar.collect(engine="streaming")
    calendar_days = set(calendar_frame["d"].to_list())
    missing_calendar_days = sorted(set(day_columns).difference(calendar_days))

    prices = pl.scan_csv(prices_path).filter(pl.col("store_id") == store_id)
    price_summary = prices.select(
        pl.len().alias("price_rows"),
        pl.struct(["store_id", "item_id", "wm_yr_wk"])
        .n_unique()
        .alias("unique_price_keys"),
        (pl.col("sell_price") <= 0).sum().alias("nonpositive_price_rows"),
        pl.col("sell_price").is_null().sum().alias("null_price_rows"),
    ).collect(engine="streaming").row(0, named=True)

    blocking = {
        "store_missing": sales_summary["store_series_rows"] == 0,
        "duplicate_sales_ids": (
            sales_summary["store_series_rows"] - sales_summary["unique_ids"]
        ),
        "null_sales_ids": sales_summary["null_ids"],
        "duplicate_calendar_days": (
            calendar_frame.height - calendar_frame["d"].n_unique()
        ),
        "null_calendar_dates": calendar_frame["date"].null_count(),
        "missing_calendar_days": missing_calendar_days,
        "duplicate_price_keys": (
            price_summary["price_rows"] - price_summary["unique_price_keys"]
        ),
        "nonpositive_price_rows": price_summary["nonpositive_price_rows"],
        "null_price_rows": price_summary["null_price_rows"],
    }
    passed = (
        not blocking["store_missing"]
        and blocking["duplicate_sales_ids"] == 0
        and blocking["null_sales_ids"] == 0
        and blocking["duplicate_calendar_days"] == 0
        and blocking["null_calendar_dates"] == 0
        and not blocking["missing_calendar_days"]
        and blocking["duplicate_price_keys"] == 0
        and blocking["nonpositive_price_rows"] == 0
        and blocking["null_price_rows"] == 0
    )
    return {
        "status": "passed" if passed else "failed",
        "sales_file": sales_path.name,
        "calendar_file": calendar_path.name,
        "prices_file": prices_path.name,
        "store_series_rows": sales_summary["store_series_rows"],
        "unique_items": sales_summary["unique_items"],
        "day_column_count": len(day_columns),
        "calendar_row_count": calendar_frame.height,
        "store_price_rows": price_summary["price_rows"],
        "blocking_checks": blocking,
    }


def build_quality_report(
    frame: pl.DataFrame,
    manifest: pl.DataFrame,
    config: ProjectConfig,
    raw_validation: dict[str, Any],
    dataset_version: str,
    reference_end_date: Any,
    generated_at: datetime,
) -> dict[str, Any]:
    keys = ["store_id", "sku_id"]
    selected_manifest = manifest.filter(pl.col("included"))
    selected_keys = selected_manifest.select(keys)
    frame_keys = frame.select(keys).unique()
    date_count = frame["date"].n_unique()
    per_series_dates = frame.group_by(keys).agg(
        pl.col("date").n_unique().alias("date_count"),
        pl.col("category").n_unique().alias("category_count"),
    )
    empty_required_rows = frame.filter(
        pl.any_horizontal(
            [
                pl.col(column).fill_null("").str.len_chars() == 0
                for column in ("store_id", "sku_id", "category", "source")
            ]
        )
    ).height
    unordered_rows = (
        frame.lazy()
        .with_columns(pl.col("date").diff().over(keys).alias("_date_diff"))
        .filter(pl.col("_date_diff").dt.total_days() < 0)
        .select(pl.len())
        .collect()
        .item()
    )
    nonfinite_quantity_rows = frame.filter(
        pl.col("quantity_sold").is_nan() | pl.col("quantity_sold").is_infinite()
    ).height
    nonfinite_price_rows = frame.filter(
        pl.col("unit_price").is_not_null()
        & (pl.col("unit_price").is_nan() | pl.col("unit_price").is_infinite())
    ).height
    nonpositive_price_rows = frame.filter(
        pl.col("unit_price").is_not_null() & (pl.col("unit_price") <= 0)
    ).height
    event_semantic_mismatch_rows = frame.filter(
        (pl.col("event_flag") & pl.col("event_name").is_null())
        | (~pl.col("event_flag") & pl.col("event_name").is_not_null())
    ).height
    missing_selected_keys = selected_keys.join(frame_keys, on=keys, how="anti").height
    unexpected_frame_keys = frame_keys.join(selected_keys, on=keys, how="anti").height
    manifest_version_mismatch_rows = manifest.filter(
        pl.col("dataset_version") != dataset_version
    ).height

    blocking_checks = {
        "raw_validation_status": raw_validation["status"],
        "selected_series_count": selected_manifest.height,
        "empty_required_rows": empty_required_rows,
        "nonfinite_quantity_rows": nonfinite_quantity_rows,
        "nonfinite_price_rows": nonfinite_price_rows,
        "nonpositive_price_rows": nonpositive_price_rows,
        "incomplete_series_count": per_series_dates.filter(
            pl.col("date_count") != date_count
        ).height,
        "category_instability_series_count": per_series_dates.filter(
            pl.col("category_count") != 1
        ).height,
        "unordered_rows": unordered_rows,
        "event_semantic_mismatch_rows": event_semantic_mismatch_rows,
        "missing_selected_keys": missing_selected_keys,
        "unexpected_frame_keys": unexpected_frame_keys,
        "manifest_version_mismatch_rows": manifest_version_mismatch_rows,
    }
    numeric_blockers = [
        value
        for key, value in blocking_checks.items()
        if key not in {"raw_validation_status", "selected_series_count"}
    ]
    passed = (
        raw_validation["status"] == "passed"
        and selected_manifest.height > 0
        and all(value == 0 for value in numeric_blockers)
    )

    active_frame = (
        frame.lazy()
        .join(
            selected_manifest.lazy().select(keys + ["active_start_date"]),
            on=keys,
            how="inner",
        )
        .filter(pl.col("date") >= pl.col("active_start_date"))
    )
    zero_runs = (
        active_frame.select(keys + ["quantity_sold"])
        .with_columns(
            (pl.col("quantity_sold") > 0)
            .cast(pl.Int64)
            .cum_sum()
            .over(keys)
            .alias("_positive_group")
        )
        .filter(pl.col("quantity_sold") == 0)
        .group_by(keys + ["_positive_group"])
        .agg(pl.len().alias("zero_run_days"))
        .group_by(keys)
        .agg(pl.col("zero_run_days").max().alias("max_zero_run_days"))
        .collect(engine="streaming")
    )
    long_zero_series = zero_runs.filter(
        pl.col("max_zero_run_days") > config.validation.long_zero_run_warning_days
    ).height
    high_missing_price_series = selected_manifest.filter(
        pl.col("active_missing_price_ratio")
        > config.validation.series_missing_price_warning_ratio
    ).height
    inactive_series = selected_manifest.filter(
        pl.col("trailing_zero_days") > config.validation.inactive_tail_warning_days
    ).height
    canonical_missing_price_ratio = frame["unit_price"].is_null().mean()
    active_missing_price_ratio = (
        active_frame.select(pl.col("unit_price").is_null().mean())
        .collect()
        .item()
    )
    quantity_threshold = frame["quantity_sold"].quantile(
        config.validation.extreme_quantity_quantile
    )
    extreme_quantity_rows = frame.filter(
        pl.col("quantity_sold") > quantity_threshold
    ).height
    extreme_price_change_rows = (
        frame.lazy()
        .filter(pl.col("unit_price").is_not_null())
        .with_columns(
            (
                pl.col("unit_price")
                / pl.col("unit_price").shift(1).over(keys)
                - 1
            )
            .abs()
            .alias("_price_change")
        )
        .filter(
            pl.col("_price_change")
            > config.validation.extreme_price_change_ratio
        )
        .select(pl.len())
        .collect()
        .item()
    )

    warnings: list[dict[str, Any]] = []
    if (
        active_missing_price_ratio
        > config.validation.global_missing_price_warning_ratio
    ):
        warnings.append(
            {
                "code": "GLOBAL_MISSING_PRICE",
                "value": active_missing_price_ratio,
                "threshold": config.validation.global_missing_price_warning_ratio,
            }
        )
    for code, value, threshold in (
        (
            "HIGH_MISSING_PRICE_SERIES",
            high_missing_price_series,
            config.validation.series_missing_price_warning_ratio,
        ),
        (
            "LONG_ZERO_RUN_SERIES",
            long_zero_series,
            config.validation.long_zero_run_warning_days,
        ),
        (
            "INACTIVE_TAIL_SERIES",
            inactive_series,
            config.validation.inactive_tail_warning_days,
        ),
        (
            "EXTREME_QUANTITY_ROWS",
            extreme_quantity_rows,
            quantity_threshold,
        ),
        (
            "EXTREME_PRICE_CHANGE_ROWS",
            extreme_price_change_rows,
            config.validation.extreme_price_change_ratio,
        ),
    ):
        if value > 0:
            warnings.append({"code": code, "count": value, "threshold": threshold})

    return {
        "status": "passed" if passed else "failed",
        "dataset_version": dataset_version,
        "generated_at": generated_at.isoformat(),
        "reference_end_date": str(reference_end_date),
        "row_count": frame.height,
        "series_count": frame_keys.height,
        "date_count": date_count,
        "blocking_checks": blocking_checks,
        "raw_validation": raw_validation,
        "profile": {
            "canonical_missing_price_ratio": canonical_missing_price_ratio,
            "active_missing_price_ratio": active_missing_price_ratio,
            "high_missing_price_series_count": high_missing_price_series,
            "long_zero_run_series_count": long_zero_series,
            "inactive_tail_series_count": inactive_series,
            "quantity_extreme_threshold": quantity_threshold,
            "extreme_quantity_rows": extreme_quantity_rows,
            "extreme_price_change_rows": extreme_price_change_rows,
            "max_zero_run_days": zero_runs["max_zero_run_days"].max(),
            "optional_null_ratios": {
                column: frame[column].is_null().mean()
                for column in (
                    "unit_price",
                    "promotion_flag",
                    "stock_on_hand",
                    "stockout_flag",
                    "unit_cost",
                )
            },
        },
        "warning_count": len(warnings),
        "warnings": warnings,
    }
