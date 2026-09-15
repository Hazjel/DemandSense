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
