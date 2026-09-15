from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from demandsense.evaluation.features import (
    FEATURE_SETS,
    KEYS,
    MAX_TARGET_LAG,
    PRICE_FEATURES,
)
from demandsense.evaluation.metrics import scaling_denominators
from demandsense.evaluation.protocol import EvaluationProtocol, FoldSpec


@dataclass
class FoldContext:
    frame: pl.DataFrame
    histories: list[np.ndarray]
    price_histories: list[np.ndarray]
    actual: np.ndarray
    rmsse_scales: np.ndarray
    mase_scales: np.ndarray
    weights: np.ndarray


def load_fold_context(
    protocol: EvaluationProtocol,
    fold: FoldSpec,
    catalog: pl.DataFrame,
    context_days: int,
) -> FoldContext:
    selected_catalog = catalog.select(
        "store_id",
        "sku_id",
        "segment",
        "active_start_date",
        "sku_code",
        "category_code",
        "subcategory_code",
    )
    history_filter = pl.col("date") <= fold.train_end
    evaluation_filter = pl.col("date").is_between(
        fold.evaluation_start, fold.evaluation_end, closed="both"
    )
    weight_filter = pl.col("date").is_between(
        fold.train_end - timedelta(days=protocol.metrics.weight_window_days - 1),
        fold.train_end,
        closed="both",
    )
    source = (
        pl.scan_parquet(protocol.dataset.demand_path)
        .filter(pl.col("date") <= fold.evaluation_end)
        .select(
            "date",
            "store_id",
            "sku_id",
            "quantity_sold",
            "unit_price",
            "event_flag",
            "snap_eligible",
        )
        .join(selected_catalog.lazy(), on=KEYS, how="inner")
        .filter(pl.col("date") >= pl.col("active_start_date"))
    )
    grouped = (
        source.group_by(KEYS)
        .agg(
            pl.col("quantity_sold")
            .filter(history_filter)
            .sort_by(pl.col("date").filter(history_filter))
            .tail(context_days)
            .alias("history"),
            pl.col("quantity_sold")
            .filter(history_filter)
            .sort_by(pl.col("date").filter(history_filter))
            .alias("scale_history"),
            pl.col("unit_price")
            .filter(history_filter)
            .sort_by(pl.col("date").filter(history_filter))
            .tail(context_days)
            .alias("price_history"),
            pl.col("quantity_sold")
            .filter(evaluation_filter)
            .sort_by(pl.col("date").filter(evaluation_filter))
            .alias("actual"),
            pl.col("event_flag")
            .filter(evaluation_filter)
            .sort_by(pl.col("date").filter(evaluation_filter))
            .alias("future_event"),
            pl.col("snap_eligible")
            .filter(evaluation_filter)
            .sort_by(pl.col("date").filter(evaluation_filter))
            .alias("future_snap"),
            pl.col("segment").first(),
            pl.col("sku_code").first(),
            pl.col("category_code").first(),
            pl.col("subcategory_code").first(),
            (
                pl.col("quantity_sold")
                * pl.col("unit_price").fill_null(0.0)
            )
            .filter(weight_filter)
            .sum()
            .alias("weight_revenue"),
        )
        .collect(engine="streaming")
        .sort(*KEYS)
    )
    if grouped.height != catalog.height:
        raise ValueError(
            f"{fold.fold_id} context has {grouped.height} series; expected {catalog.height}"
        )
    invalid = grouped.filter(
        (pl.col("history").list.len() < MAX_TARGET_LAG)
        | (pl.col("actual").list.len() != protocol.temporal.horizon_days)
        | (pl.col("future_event").list.len() != protocol.temporal.horizon_days)
        | (pl.col("future_snap").list.len() != protocol.temporal.horizon_days)
    ).height
    if invalid:
        raise ValueError(f"{fold.fold_id} has {invalid} invalid context rows")

    histories = [
        np.asarray(values, dtype=np.float32) for values in grouped["history"].to_list()
    ]
    scales = [
        scaling_denominators(values)
        for values in grouped["scale_history"].to_list()
    ]
    price_histories = []
    for values in grouped["price_history"].to_list():
        price_array = np.asarray(
            [np.nan if value is None else value for value in values], dtype=np.float32
        )
        if np.isnan(price_array).any():
            valid = np.flatnonzero(~np.isnan(price_array))
            if valid.size:
                price_array[: valid[0]] = price_array[valid[0]]
                for index in range(valid[0] + 1, len(price_array)):
                    if np.isnan(price_array[index]):
                        price_array[index] = price_array[index - 1]
            else:
                price_array.fill(0.0)
        price_histories.append(price_array)
    actual = np.asarray(grouped["actual"].to_list(), dtype=np.float32)
    return FoldContext(
        frame=grouped.drop("scale_history"),
        histories=histories,
        price_histories=price_histories,
        actual=actual,
        rmsse_scales=np.asarray([value[0] for value in scales], dtype=np.float64),
        mase_scales=np.asarray([value[1] for value in scales], dtype=np.float64),
        weights=grouped["weight_revenue"].to_numpy(),
    )


def _days_since_nonzero(values: np.ndarray) -> int:
    positive = np.flatnonzero(values > 0)
    return len(values) - 1 - int(positive[-1]) if positive.size else len(values)


def _initial_state(context: FoldContext) -> dict[str, np.ndarray]:
    target_state = np.stack([values[-MAX_TARGET_LAG:] for values in context.histories])
    target_sums = np.asarray([values.sum() for values in context.histories], dtype=np.float64)
    target_counts = np.asarray([len(values) for values in context.histories], dtype=np.int32)
    days_since = np.asarray(
        [_days_since_nonzero(values) for values in context.histories], dtype=np.float32
    )
    price_state = np.stack([values[-7:] for values in context.price_histories])
    price_sums = np.asarray(
        [values.sum() for values in context.price_histories], dtype=np.float64
    )
    price_counts = np.asarray(
        [len(values) for values in context.price_histories], dtype=np.int32
    )
    return {
        "target_state": target_state,
        "target_sums": target_sums,
        "target_counts": target_counts,
        "days_since": days_since,
        "price_state": price_state,
        "price_sums": price_sums,
        "price_counts": price_counts,
    }


def recursive_feature_matrix(
    context: FoldContext,
    state: dict[str, np.ndarray],
    fold: FoldSpec,
    horizon_index: int,
) -> dict[str, np.ndarray]:
    target_state = state["target_state"]
    price_state = state["price_state"]
    forecast_date = fold.evaluation_start + timedelta(days=horizon_index)
    feature_values: dict[str, np.ndarray] = {
        "sku_code": context.frame["sku_code"].to_numpy(),
        "category_code": context.frame["category_code"].to_numpy(),
        "subcategory_code": context.frame["subcategory_code"].to_numpy(),
        "lag_1": target_state[:, -1],
        "lag_7": target_state[:, -7],
        "lag_14": target_state[:, -14],
        "lag_28": target_state[:, -28],
        "lag_56": target_state[:, -56],
        "rolling_mean_7": target_state[:, -7:].mean(axis=1),
        "rolling_mean_28": target_state[:, -28:].mean(axis=1),
        "rolling_mean_56": target_state.mean(axis=1),
        "rolling_std_7": target_state[:, -7:].std(axis=1),
        "rolling_std_28": target_state[:, -28:].std(axis=1),
        "rolling_std_56": target_state.std(axis=1),
        "nonzero_rate_28": (target_state[:, -28:] > 0).mean(axis=1),
        "days_since_nonzero": state["days_since"],
        "context_mean": state["target_sums"] / state["target_counts"],
        "day_of_week": np.full(context.frame.height, forecast_date.isoweekday()),
        "week_of_year": np.full(
            context.frame.height, forecast_date.isocalendar().week
        ),
        "month": np.full(context.frame.height, forecast_date.month),
        "day_of_month": np.full(context.frame.height, forecast_date.day),
        "is_weekend": np.full(
            context.frame.height, float(forecast_date.isoweekday() >= 6)
        ),
        "event_flag_feature": np.asarray(
            [values[horizon_index] for values in context.frame["future_event"]],
            dtype=np.float32,
        ),
        "snap_eligible_feature": np.asarray(
            [values[horizon_index] for values in context.frame["future_snap"]],
            dtype=np.float32,
        ),
        "price_lag_1": price_state[:, -1],
        "price_change_7": price_state[:, -1] / price_state[:, -7] - 1.0,
        "relative_price": (
            price_state[:, -1]
            / (state["price_sums"] / state["price_counts"])
        ),
    }
    return feature_values


def update_recursive_state(
    state: dict[str, np.ndarray], predictions: np.ndarray
) -> None:
    clipped = np.maximum(predictions.astype(np.float32), 0.0)
    state["target_state"] = np.concatenate(
        [state["target_state"][:, 1:], clipped[:, None]], axis=1
    )
    state["target_sums"] += clipped
    state["target_counts"] += 1
    state["days_since"] = np.where(clipped > 0, 0.0, state["days_since"] + 1.0)
    last_price = state["price_state"][:, -1].copy()
    state["price_state"] = np.concatenate(
        [state["price_state"][:, 1:], last_price[:, None]], axis=1
    )
    state["price_sums"] += last_price
    state["price_counts"] += 1


def train_predict_xgboost(
    training: pl.DataFrame,
    context: FoldContext,
    fold: FoldSpec,
    feature_set: str,
    parameters: dict[str, Any],
    num_boost_round: int,
    model_path: Path,
) -> tuple[np.ndarray, dict[str, Any]]:
    import xgboost as xgb

    feature_names = FEATURE_SETS[feature_set]
    medians = {
        feature: float(training[feature].median() or 0.0)
        for feature in PRICE_FEATURES
        if feature in feature_names
    }
    feature_frame = training.select(feature_names).with_columns(
        [pl.col(name).fill_null(value) for name, value in medians.items()]
    )
    features = np.asarray(feature_frame.to_numpy(), dtype=np.float32)
    target = training["target"].to_numpy().astype(np.float32, copy=False)
    started = time.perf_counter()
    train_matrix = xgb.QuantileDMatrix(
        features,
        target,
        feature_names=feature_names,
        max_bin=parameters["max_bin"],
    )
    booster = xgb.train(
        parameters,
        train_matrix,
        num_boost_round=num_boost_round,
    )
    state = _initial_state(context)
    forecasts = np.empty(
        (context.frame.height, context.actual.shape[1]), dtype=np.float32
    )
    for horizon_index in range(context.actual.shape[1]):
        values = recursive_feature_matrix(context, state, fold, horizon_index)
        inference_frame = pl.DataFrame(
            {name: values[name] for name in feature_names}
        ).with_columns(
            [pl.col(name).fill_null(value) for name, value in medians.items()]
        )
        inference = np.asarray(inference_frame.to_numpy(), dtype=np.float32)
        prediction_matrix = xgb.QuantileDMatrix(
            inference,
            feature_names=feature_names,
            max_bin=parameters["max_bin"],
            ref=train_matrix,
        )
        predictions = np.maximum(booster.predict(prediction_matrix), 0.0)
        forecasts[:, horizon_index] = predictions
        update_recursive_state(state, predictions)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(model_path)
    return forecasts, {
        "training_rows": training.height,
        "feature_count": len(feature_names),
        "feature_names": feature_names,
        "price_imputation_medians": medians,
        "runtime_seconds": time.perf_counter() - started,
        "xgboost_version": xgb.__version__,
    }


def predict_chronos_bolt(
    pipeline: Any,
    context: FoldContext,
    prediction_length: int,
    context_length: int,
    batch_size: int,
    quantile_levels: list[float],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    import torch

    started = time.perf_counter()
    means = []
    quantile_batches = []
    with torch.inference_mode():
        for start in range(0, len(context.histories), batch_size):
            batch = [
                torch.tensor(values[-context_length:], dtype=torch.float32)
                for values in context.histories[start : start + batch_size]
            ]
            quantiles, mean = pipeline.predict_quantiles(
                batch,
                prediction_length=prediction_length,
                quantile_levels=quantile_levels,
            )
            quantile_batches.append(quantiles.detach().cpu().numpy())
            means.append(mean.detach().cpu().numpy())
    mean_array = np.maximum(np.concatenate(means, axis=0), 0.0).astype(np.float32)
    quantile_array = np.maximum(
        np.concatenate(quantile_batches, axis=0), 0.0
    ).astype(np.float32)
    crossing_rows = int(np.any(np.diff(quantile_array, axis=2) < 0, axis=2).sum())
    quantile_array.sort(axis=2)
    return mean_array, quantile_array, {
        "runtime_seconds": time.perf_counter() - started,
        "batch_size": batch_size,
        "context_length": context_length,
        "quantile_crossing_rows_corrected": crossing_rows,
    }
