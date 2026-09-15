import math

import pytest

from demandsense.evaluation.baselines import croston_sba
from demandsense.evaluation.metrics import forecast_metrics, scaling_denominators


def test_scaling_and_forecast_metrics() -> None:
    rmsse_scale, mase_scale = scaling_denominators([0.0, 1.0, 2.0, 3.0])

    metrics = forecast_metrics(
        actual=[4.0, 5.0],
        forecast=[3.0, 3.0],
        rmsse_scale=rmsse_scale,
        mase_scale=mase_scale,
    )

    assert rmsse_scale == 1.0
    assert mase_scale == 1.0
    assert metrics["rmsse"] == pytest.approx(math.sqrt(2.5))
    assert metrics["mase"] == 1.5
    assert metrics["wape"] == pytest.approx(1 / 3)
    assert metrics["normalized_bias"] == pytest.approx(-1 / 3)


def test_zero_denominators_are_reported_as_null() -> None:
    rmsse_scale, mase_scale = scaling_denominators([0.0, 0.0, 0.0])
    metrics = forecast_metrics([0.0, 0.0], [0.0, 1.0], rmsse_scale, mase_scale)

    assert rmsse_scale is None
    assert mase_scale is None
    assert metrics["rmsse"] is None
    assert metrics["mase"] is None
    assert metrics["wape"] is None
    assert metrics["normalized_bias"] is None


def test_croston_sba_is_nonnegative_and_constant_over_horizon() -> None:
    forecast = croston_sba([0.0, 2.0, 0.0, 0.0, 2.0], horizon=3, alpha=0.1)

    assert len(forecast) == 3
    assert forecast[0] == forecast[1] == forecast[2]
    assert forecast[0] > 0
    assert croston_sba([0.0, 0.0], horizon=2) == [0.0, 0.0]
