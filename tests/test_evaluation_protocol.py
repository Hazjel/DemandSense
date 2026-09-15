from datetime import date

import pytest
from pydantic import ValidationError

from demandsense.evaluation.baselines import seasonal_naive
from demandsense.evaluation.protocol import EvaluationProtocol, load_evaluation_protocol


def test_seasonal_naive_is_recursive_beyond_first_lag() -> None:
    history = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]

    predictions = seasonal_naive(history, horizon=10, lag=7)

    assert predictions == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 1.0, 2.0, 3.0]


@pytest.mark.parametrize(
    ("history", "horizon", "lag"),
    [([], 1, 1), ([1.0], 0, 1), ([1.0], 1, 0), ([1.0], 1, 2)],
)
def test_seasonal_naive_rejects_invalid_inputs(
    history: list[float], horizon: int, lag: int
) -> None:
    with pytest.raises(ValueError):
        seasonal_naive(history, horizon=horizon, lag=lag)


def test_frozen_protocol_has_expected_boundaries() -> None:
    protocol = load_evaluation_protocol("configs/evaluation.yaml")

    assert protocol.status == "frozen"
    assert protocol.temporal.folds[0].train_end == date(2016, 1, 31)
    assert protocol.temporal.folds[-1].evaluation_end == date(2016, 5, 22)
    assert protocol.temporal.folds[-1].locked
    assert protocol.feature_policy.target_features_minimum_lag_days == 1
    assert protocol.seasonal_naive.recursive


def test_protocol_rejects_target_window_overlap() -> None:
    protocol = load_evaluation_protocol("configs/evaluation.yaml")
    payload = protocol.model_dump(mode="json")
    payload["temporal"]["folds"][1]["evaluation_start"] = "2016-02-28"

    with pytest.raises(ValidationError):
        EvaluationProtocol.model_validate(payload)
