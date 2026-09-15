import json
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
    assert metadata["dataset_version"] == result["dataset_version"]
    assert metadata["schema_version"] == "1.0.0"
    assert metadata["row_count"] == 2
    assert metadata["series_count"] == 1
    assert metadata["validation_status"] == "passed"
    assert metadata["manifest_validation_status"] == "passed"
    assert metadata["selected_series_manifest_checksum"]
