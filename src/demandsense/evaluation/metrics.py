from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def scaling_denominators(
    history: Sequence[float],
) -> tuple[float | None, float | None]:
    values = [float(value) for value in history]
    first_positive = next(
        (index for index, value in enumerate(values) if value > 0), None
    )
    if first_positive is None or len(values) - first_positive < 2:
        return None, None

    differences = [
        current - previous
        for previous, current in zip(
            values[first_positive:-1], values[first_positive + 1 :], strict=True
        )
    ]
    squared_scale = sum(value * value for value in differences) / len(differences)
    absolute_scale = sum(abs(value) for value in differences) / len(differences)
    return (
        squared_scale if squared_scale > 0 else None,
        absolute_scale if absolute_scale > 0 else None,
    )


def forecast_metrics(
    actual: Sequence[float],
    forecast: Sequence[float],
    rmsse_scale: float | None,
    mase_scale: float | None,
) -> dict[str, Any]:
    actual_values = [float(value) for value in actual]
    forecast_values = [float(value) for value in forecast]
    if not actual_values:
        raise ValueError("actual must not be empty")
    if len(actual_values) != len(forecast_values):
        raise ValueError("actual and forecast must have equal lengths")

    errors = [
        predicted - observed
        for observed, predicted in zip(
            actual_values, forecast_values, strict=True
        )
    ]
    absolute_error_sum = sum(abs(value) for value in errors)
    squared_error_mean = sum(value * value for value in errors) / len(errors)
    absolute_error_mean = absolute_error_sum / len(errors)
    actual_sum = sum(actual_values)
    error_sum = sum(errors)
    return {
        "rmsse": (
            math.sqrt(squared_error_mean / rmsse_scale)
            if rmsse_scale is not None
            else None
        ),
        "mase": (
            absolute_error_mean / mase_scale
            if mase_scale is not None
            else None
        ),
        "wape": absolute_error_sum / actual_sum if actual_sum > 0 else None,
        "normalized_bias": error_sum / actual_sum if actual_sum > 0 else None,
        "actual_sum": actual_sum,
        "forecast_sum": sum(forecast_values),
        "absolute_error_sum": absolute_error_sum,
        "squared_error_sum": squared_error_mean * len(errors),
        "error_sum": error_sum,
        "observation_count": len(errors),
    }
