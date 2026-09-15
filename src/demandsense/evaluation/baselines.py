from __future__ import annotations

from collections.abc import Sequence


def seasonal_naive(
    history: Sequence[float],
    horizon: int,
    lag: int,
) -> list[float]:
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if lag < 1:
        raise ValueError("lag must be positive")
    if len(history) < lag:
        raise ValueError(f"history must contain at least {lag} observations")

    state = [float(value) for value in history]
    predictions: list[float] = []
    for _ in range(horizon):
        prediction = state[-lag]
        predictions.append(prediction)
        state.append(prediction)
    return predictions


def croston_sba(
    history: Sequence[float],
    horizon: int,
    alpha: float = 0.1,
) -> list[float]:
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    if not history:
        raise ValueError("history must not be empty")

    values = [float(value) for value in history]
    if any(value < 0 for value in values):
        raise ValueError("history must be non-negative")
    first_positive = next(
        (index for index, value in enumerate(values) if value > 0), None
    )
    if first_positive is None:
        return [0.0] * horizon

    demand = values[first_positive]
    interval = float(first_positive + 1)
    elapsed = 1
    for value in values[first_positive + 1 :]:
        if value > 0:
            demand += alpha * (value - demand)
            interval += alpha * (elapsed - interval)
            elapsed = 1
        else:
            elapsed += 1

    forecast = max(0.0, (1.0 - alpha / 2.0) * demand / interval)
    return [forecast] * horizon
