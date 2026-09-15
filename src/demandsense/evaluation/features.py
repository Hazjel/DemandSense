from __future__ import annotations

from datetime import timedelta

import polars as pl

from demandsense.evaluation.protocol import EvaluationProtocol, FoldSpec

KEYS = ["store_id", "sku_id"]
TARGET_FEATURES = [
    "sku_code",
    "category_code",
    "subcategory_code",
    "lag_1",
    "lag_7",
    "lag_14",
    "lag_28",
    "lag_56",
    "rolling_mean_7",
    "rolling_mean_28",
    "rolling_mean_56",
    "rolling_std_7",
    "rolling_std_28",
    "rolling_std_56",
    "nonzero_rate_28",
    "days_since_nonzero",
    "context_mean",
]
CALENDAR_FEATURES = [
    "day_of_week",
    "week_of_year",
    "month",
    "day_of_month",
    "is_weekend",
    "event_flag_feature",
    "snap_eligible_feature",
]
PRICE_FEATURES = ["price_lag_1", "price_change_7", "relative_price"]
ALL_FEATURES = TARGET_FEATURES + CALENDAR_FEATURES + PRICE_FEATURES
FEATURE_SETS = {
    "xgb_lag": TARGET_FEATURES,
    "xgb_calendar": TARGET_FEATURES + CALENDAR_FEATURES,
    "xgb_full": ALL_FEATURES,
}
MAX_TARGET_LAG = 56


def load_series_catalog(protocol: EvaluationProtocol) -> pl.DataFrame:
    manifest = pl.read_parquet(protocol.dataset.series_manifest_path).filter(
        pl.col("included")
    )
    attributes = (
        pl.scan_parquet(protocol.dataset.demand_path)
        .select("store_id", "sku_id", "category", "subcategory")
        .unique()
        .collect(engine="streaming")
    )
    catalog = (
        manifest.select(
            "store_id", "sku_id", "segment", "active_start_date"
        )
        .join(attributes, on=KEYS, how="inner", validate="1:1")
        .sort(*KEYS)
        .with_row_index("sku_code")
    )
    category_map = {
        value: index
        for index, value in enumerate(sorted(catalog["category"].unique()))
    }
    subcategory_map = {
        value: index
        for index, value in enumerate(sorted(catalog["subcategory"].unique()))
    }
    return catalog.with_columns(
        pl.col("category")
        .replace_strict(category_map, return_dtype=pl.UInt16)
        .alias("category_code"),
        pl.col("subcategory")
        .replace_strict(subcategory_map, return_dtype=pl.UInt16)
        .alias("subcategory_code"),
    )


def add_causal_features(frame: pl.LazyFrame) -> pl.LazyFrame:
    quantity = pl.col("quantity_sold")
    shifted_quantity = quantity.shift(1)
    previous_positive_date = (
        pl.when(quantity > 0)
        .then(pl.col("date"))
        .otherwise(pl.lit(None, dtype=pl.Date))
        .shift(1)
        .forward_fill()
        .over(KEYS, order_by="date")
    )
    price_lag_1 = pl.col("unit_price").shift(1).over(KEYS, order_by="date")
    price_lag_7 = pl.col("unit_price").shift(7).over(KEYS, order_by="date")
    shifted_price = pl.col("unit_price").shift(1)
    context_price_mean = (
        shifted_price.cum_sum() / shifted_price.cum_count()
    ).over(KEYS, order_by="date")
    expressions: list[pl.Expr] = [
        quantity.shift(lag).over(KEYS, order_by="date").alias(f"lag_{lag}")
        for lag in (1, 7, 14, 28, 56)
    ]
    for window in (7, 28, 56):
        expressions.extend(
            [
                shifted_quantity
                .rolling_mean(window, min_samples=window)
                .over(KEYS, order_by="date")
                .alias(f"rolling_mean_{window}"),
                shifted_quantity
                .rolling_std(window, min_samples=window, ddof=0)
                .over(KEYS, order_by="date")
                .alias(f"rolling_std_{window}"),
            ]
        )
    expressions.extend(
        [
            (shifted_quantity > 0)
            .cast(pl.Float32)
            .rolling_mean(28, min_samples=28)
            .over(KEYS, order_by="date")
            .alias("nonzero_rate_28"),
            (pl.col("date") - previous_positive_date)
            .dt.total_days()
            .fill_null(MAX_TARGET_LAG + 1)
            .alias("days_since_nonzero"),
            (
                shifted_quantity.cum_sum()
                / shifted_quantity.cum_count()
            )
            .over(KEYS, order_by="date")
            .alias("context_mean"),
            pl.col("date").dt.weekday().alias("day_of_week"),
            pl.col("date").dt.week().alias("week_of_year"),
            pl.col("date").dt.month().alias("month"),
            pl.col("date").dt.day().alias("day_of_month"),
            (pl.col("date").dt.weekday() >= 6)
            .cast(pl.Float32)
            .alias("is_weekend"),
            pl.col("event_flag")
            .fill_null(False)
            .cast(pl.Float32)
            .alias("event_flag_feature"),
            pl.col("snap_eligible")
            .fill_null(False)
            .cast(pl.Float32)
            .alias("snap_eligible_feature"),
            price_lag_1.alias("price_lag_1"),
            (price_lag_1 / price_lag_7 - 1.0).alias("price_change_7"),
            (price_lag_1 / context_price_mean).alias("relative_price"),
        ]
    )
    return frame.with_columns(expressions)


def build_training_frame(
    protocol: EvaluationProtocol,
    fold: FoldSpec,
    catalog: pl.DataFrame,
    training_window_days: int,
) -> pl.DataFrame:
    training_start = fold.train_end - timedelta(days=training_window_days - 1)
    context_start = training_start - timedelta(days=MAX_TARGET_LAG)
    catalog_columns = [
        "store_id",
        "sku_id",
        "active_start_date",
        "sku_code",
        "category_code",
        "subcategory_code",
    ]
    source = (
        pl.scan_parquet(protocol.dataset.demand_path)
        .filter(pl.col("date").is_between(context_start, fold.train_end, closed="both"))
        .select(
            "date",
            "store_id",
            "sku_id",
            "quantity_sold",
            "unit_price",
            "event_flag",
            "snap_eligible",
        )
        .join(catalog.lazy().select(catalog_columns), on=KEYS, how="inner")
        .filter(pl.col("date") >= pl.col("active_start_date"))
        .sort(*KEYS, "date")
    )
    featured = add_causal_features(source).filter(pl.col("date") >= training_start)
    return (
        featured.drop_nulls(TARGET_FEATURES)
        .select(
            "date",
            "store_id",
            "sku_id",
            pl.col("quantity_sold").alias("target"),
            *ALL_FEATURES,
        )
        .collect(engine="streaming")
        .sort(*KEYS, "date")
    )
