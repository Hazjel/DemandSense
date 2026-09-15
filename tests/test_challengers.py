from datetime import date

from demandsense.evaluation.challengers import _prediction_frame


def test_prediction_frame_infers_quantiles_after_many_point_rows() -> None:
    records = []
    for index in range(101):
        records.append(
            {
                "fold_id": "development_1",
                "model_id": "xgb_lag",
                "store_id": "CA_1",
                "sku_id": f"ITEM_{index:03d}",
                "horizon": 1,
                "forecast_date": date(2026, 1, 1),
                "q10": None,
                "q50": None,
                "q90": None,
            }
        )
    records.append(
        {
            "fold_id": "development_1",
            "model_id": "chronos_bolt_small",
            "store_id": "CA_1",
            "sku_id": "ITEM_999",
            "horizon": 1,
            "forecast_date": date(2026, 1, 1),
            "q10": 0.0,
            "q50": 1.0,
            "q90": 2.0,
        }
    )

    frame = _prediction_frame(records)

    assert frame.schema["q10"].is_float()
    assert frame.filter(frame["model_id"] == "chronos_bolt_small")["q90"].item() == 2.0
