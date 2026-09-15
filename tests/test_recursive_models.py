from datetime import date

import numpy as np
import polars as pl

from demandsense.evaluation.models import (
    FoldContext,
    _initial_state,
    recursive_feature_matrix,
    update_recursive_state,
)
from demandsense.evaluation.protocol import FoldSpec


def test_recursive_features_use_predictions_after_cutoff() -> None:
    frame = pl.DataFrame(
        {
            "store_id": ["CA_1"],
            "sku_id": ["ITEM_1"],
            "segment": ["fast"],
            "sku_code": [0],
            "category_code": [0],
            "subcategory_code": [0],
            "future_event": [[False, True]],
            "future_snap": [[False, False]],
        }
    )
    history = np.arange(1, 61, dtype=np.float32)
    context = FoldContext(
        frame=frame,
        histories=[history],
        price_histories=[np.full(60, 2.0, dtype=np.float32)],
        actual=np.asarray([[999.0, 999.0]], dtype=np.float32),
        rmsse_scales=np.asarray([1.0]),
        mase_scales=np.asarray([1.0]),
        weights=np.asarray([1.0]),
    )
    fold = FoldSpec(
        fold_id="development_1",
        role="development",
        train_start=date(2026, 1, 1),
        train_end=date(2026, 3, 1),
        evaluation_start=date(2026, 3, 2),
        evaluation_end=date(2026, 3, 3),
        locked=False,
    )
    state = _initial_state(context)

    first = recursive_feature_matrix(context, state, fold, 0)
    update_recursive_state(state, np.asarray([10.0], dtype=np.float32))
    second = recursive_feature_matrix(context, state, fold, 1)

    assert first["lag_1"].item() == 60.0
    assert second["lag_1"].item() == 10.0
    assert second["lag_1"].item() != context.actual[0, 0]
    assert second["event_flag_feature"].item() == 1.0
