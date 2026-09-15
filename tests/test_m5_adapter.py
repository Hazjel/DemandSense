import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from demandsense.config import load_config
from demandsense.data.m5 import M5Adapter


def _write_m5_fixture(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "id": ["FOODS_1_001_CA_1_validation", "FOODS_1_002_CA_1_validation"],
            "item_id": ["FOODS_1_001", "FOODS_1_002"],
            "dept_id": ["FOODS_1", "FOODS_1"],
            "cat_id": ["FOODS", "FOODS"],
            "store_id": ["CA_1", "CA_1"],
            "state_id": ["CA", "CA"],
            "d_1": [1, 0],
            "d_2": [2, 1],
        }
    ).write_csv(raw_dir / "sales_train_validation.csv")
    pl.DataFrame(
        {
            "date": ["2011-01-29", "2011-01-30"],
            "wm_yr_wk": [11101, 11101],
            "d": ["d_1", "d_2"],
            "event_name_1": [None, "Sporting"],
            "event_name_2": [None, None],
            "snap_CA": [0, 1],
        }
    ).write_csv(raw_dir / "calendar.csv")
    pl.DataFrame(
        {
            "store_id": ["CA_1", "CA_1"],
            "item_id": ["FOODS_1_001", "FOODS_1_002"],
            "wm_yr_wk": [11101, 11101],
            "sell_price": [2.50, 3.25],
        }
    ).write_csv(raw_dir / "sell_prices.csv")


def test_prepare_m5_fixture(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    _write_m5_fixture(raw_dir)
    base = load_config("configs/smoke.yaml")
    config = base.model_copy(
        update={
            "paths": base.paths.model_copy(
                update={"raw_dir": raw_dir, "processed_dir": processed_dir}
            ),
            "data": base.data.model_copy(update={"series_limit": 1}),
            "forecast": base.forecast.model_copy(
                update={"horizon": 1, "minimum_history_days": 1}
            ),
        }
    )

    result = M5Adapter(config).prepare()

    demand = pl.read_parquet(result["demand_path"])
    manifest = pl.read_parquet(result["manifest_path"])
    assert result["validation"]["status"] == "passed"
    assert result["manifest_validation"]["status"] == "passed"
    assert demand.height == 2
    assert demand["sku_id"].unique().to_list() == ["FOODS_1_001"]
    assert demand["unit_price"].to_list() == [2.5, 2.5]
    assert demand["event_flag"].to_list() == [False, True]
    assert demand["event_name"].to_list() == [None, "Sporting"]
    assert manifest["cohort_role"].to_list() == ["smoke"]
    assert manifest["dataset_version"].to_list() == [result["dataset_version"]]

    metadata = json.loads(Path(result["dataset_metadata_path"]).read_text())
    quality = json.loads(Path(result["quality_report_path"]).read_text())
    assert metadata["dataset_version"] == result["dataset_version"]
    assert metadata["schema_version"] == "1.1.0"
    assert metadata["row_count"] == 2
    assert metadata["series_count"] == 1
    assert metadata["validation_status"] == "passed"
    assert metadata["manifest_validation_status"] == "passed"
    assert metadata["selected_series_manifest_checksum"]
    assert metadata["quality_status"] == "passed"
    assert quality["status"] == "passed"
    assert quality["raw_validation"]["status"] == "passed"
    assert quality["blocking_checks"]["event_semantic_mismatch_rows"] == 0


def test_development_cohort_is_stratified_and_deterministic() -> None:
    base = load_config("configs/base.yaml")
    config = base.model_copy(
        update={
            "data": base.data.model_copy(
                update={"profile": "development", "series_limit": 6}
            ),
            "forecast": base.forecast.model_copy(
                update={"horizon": 1, "minimum_history_days": 1}
            ),
        }
    )
    start = date(2026, 1, 1)
    rows = []
    quantities = {
        "fast": [1.0] * 10,
        "medium": [0.0] * 5 + [1.0] * 5,
        "intermittent": [0.0] * 8 + [1.0] * 2,
    }
    for segment, values in quantities.items():
        for item_index in range(3):
            for day_index, quantity in enumerate(values):
                rows.append(
                    {
                        "date": start + timedelta(days=day_index),
                        "store_id": "CA_1",
                        "sku_id": f"{segment}_{item_index}",
                        "quantity_sold": quantity,
                        "unit_price": 1.0,
                    }
                )
    canonical = pl.DataFrame(rows)
    adapter = M5Adapter(config)

    first = adapter._build_manifest(canonical, "test-version", start + timedelta(days=8))
    second = adapter._build_manifest(canonical, "test-version", start + timedelta(days=8))
    included = first.filter(pl.col("included"))

    assert included.height == 6
    assert included.group_by("segment").len().sort("segment").to_dicts() == [
        {"segment": "fast", "len": 2},
        {"segment": "intermittent", "len": 2},
        {"segment": "medium", "len": 2},
    ]
    assert included["sku_id"].sort().to_list() == (
        second.filter(pl.col("included"))["sku_id"].sort().to_list()
    )
