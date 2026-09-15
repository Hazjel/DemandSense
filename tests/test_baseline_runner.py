import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import yaml

from demandsense.evaluation.runner import (
    run_baseline_suite,
    verify_baseline_reproducibility,
)


def _write_runner_fixture(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    start = date(2026, 1, 1)
    rows = []
    for day_index in range(12):
        for sku_index, sku_id in enumerate(("ITEM_1", "ITEM_2"), start=1):
            rows.append(
                {
                    "date": start + timedelta(days=day_index),
                    "store_id": "CA_1",
                    "sku_id": sku_id,
                    "quantity_sold": float((day_index + sku_index) % 4),
                    "unit_price": float(sku_index),
                }
            )
    demand_path = dataset_dir / "demand.parquet"
    pl.DataFrame(rows).write_parquet(demand_path)

    manifest_path = dataset_dir / "manifest.parquet"
    pl.DataFrame(
        {
            "store_id": ["CA_1", "CA_1"],
            "sku_id": ["ITEM_1", "ITEM_2"],
            "included": [True, True],
            "segment": ["fast", "fast"],
            "active_start_date": [start, start],
            "reference_end_date": [start + timedelta(days=9)] * 2,
            "eligibility_cutoff_date": [start + timedelta(days=7)] * 2,
            "eligibility_history_days": [8, 8],
        }
    ).write_parquet(manifest_path)
    manifest_checksum = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    metadata_path = dataset_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "dataset_version": "fixture-release-v1",
                "schema_version": "fixture-1",
                "eligibility_cutoff_date": "2026-01-08",
                "cohort_definition_version": "fixture-segments-v1",
            }
        ),
        encoding="utf-8",
    )
    protocol_path = tmp_path / "evaluation.yaml"
    protocol_path.write_text(
        yaml.safe_dump(
            {
                "protocol_version": "fixture-m2-v1",
                "status": "frozen",
                "dataset": {
                    "profile": "release",
                    "dataset_version": "fixture-release-v1",
                    "schema_version": "fixture-1",
                    "demand_path": str(demand_path),
                    "metadata_path": str(metadata_path),
                    "series_manifest_path": str(manifest_path),
                    "series_manifest_checksum": manifest_checksum,
                },
                "temporal": {
                    "horizon_days": 2,
                    "minimum_history_days": 4,
                    "folds": [
                        {
                            "fold_id": "development_1",
                            "role": "development",
                            "train_start": "2026-01-01",
                            "train_end": "2026-01-08",
                            "evaluation_start": "2026-01-09",
                            "evaluation_end": "2026-01-10",
                            "locked": False,
                        },
                        {
                            "fold_id": "locked_final",
                            "role": "locked_final_test",
                            "train_start": "2026-01-01",
                            "train_end": "2026-01-10",
                            "evaluation_start": "2026-01-11",
                            "evaluation_end": "2026-01-12",
                            "locked": True,
                        },
                    ],
                },
                "segments": {
                    "definition_version": "fixture-segments-v1",
                    "reference_end_date": "2026-01-10",
                    "usage": "reporting_only",
                    "fast_max_zero_ratio": 0.2,
                    "intermittent_min_zero_ratio": 0.6,
                },
                "feature_policy": {
                    "target_features_minimum_lag_days": 1,
                    "transforms_fit_scope": "fold_training_only",
                    "future_calendar": "allowed_if_known_at_decision_time",
                    "future_price": "lagged_only",
                    "segment_as_model_feature": False,
                    "locked_final_target_access": "after_champion_configuration_freeze",
                },
                "seasonal_naive": {"lags": [1, 2], "recursive": True},
                "metrics": {
                    "primary": "weighted_rmsse_store_bottom_level",
                    "secondary": ["mase", "wape", "normalized_bias"],
                    "horizon_bands": [[1, 1], [2, 2]],
                    "zero_denominator_policy": "report_null_and_count",
                    "rmsse_scale_start": "first_positive_training_observation",
                    "weight_window_days": 2,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    baseline_path = tmp_path / "baselines.yaml"
    baseline_path.write_text(
        yaml.safe_dump(
            {
                "suite_version": "fixture-m3-v1",
                "protocol_path": str(protocol_path),
                "fold_scope": "development_only",
                "locked_final_target_access": False,
                "croston": {"variant": "sba", "alpha": 0.1},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return baseline_path


def test_runner_excludes_locked_final_and_reproduces_outputs(tmp_path: Path) -> None:
    config_path = _write_runner_fixture(tmp_path)
    reference_dir = tmp_path / "reference"

    result = run_baseline_suite(config_path, reference_dir)
    reproduction = verify_baseline_reproducibility(
        config_path, reference_dir, tmp_path / "reproduction"
    )

    assert result["fold_ids"] == ["development_1"]
    assert result["prediction_row_count"] == 12
    assert result["maximum_target_date_accessed"] == "2026-01-10"
    assert not result["locked_final_target_accessed"]
    assert reproduction["status"] == "passed"
