from datetime import date, timedelta

import polars as pl
import pytest

from demandsense.evaluation.features import (
    ALL_FEATURES,
    add_causal_features,
)


def _feature_fixture(future_value: float) -> pl.DataFrame:
    start = date(2026, 1, 1)
    quantities = [float((index % 5) + 1) for index in range(70)]
    quantities[-1] = future_value
    return pl.DataFrame(
        {
            "date": [start + timedelta(days=index) for index in range(70)],
            "store_id": ["CA_1"] * 70,
            "sku_id": ["ITEM_1"] * 70,
            "quantity_sold": quantities,
            "unit_price": [2.0] * 70,
            "event_flag": [False] * 70,
            "snap_eligible": [False] * 70,
            "sku_code": [0] * 70,
            "category_code": [0] * 70,
            "subcategory_code": [0] * 70,
        }
    )


def test_causal_features_do_not_change_before_modified_future_target() -> None:
    original = add_causal_features(_feature_fixture(1.0).lazy()).collect()
    modified = add_causal_features(_feature_fixture(999.0).lazy()).collect()

    assert original.head(69).select(ALL_FEATURES).equals(
        modified.head(69).select(ALL_FEATURES)
    )
    final = original.row(-1, named=True)
    assert final["lag_1"] == 4.0
    assert final["lag_7"] == 3.0
    assert final["rolling_mean_7"] == pytest.approx(22 / 7)
